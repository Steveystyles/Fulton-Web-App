"""Apply source-reviewed wording corrections to exact unpublished Map rounds.

The input JSON names each ready entry, its current payload hash, and the old
and replacement clue text. An applied edit first makes a verified online
backup, then rechecks every precondition inside one transaction. Published
rounds and player data are never changed.
"""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Any
from urllib.parse import urlparse

from deploy import backup_manager
from tools import controlled_map_round as controlled
from tools import discover_map_places as discovery


def checked_changes(conn: sqlite3.Connection, changes: list[dict]) -> list[dict[str, Any]]:
    if not isinstance(changes, list) or not changes:
        raise ValueError("Provide at least one queued Map correction.")
    prepared = []
    seen: set[str] = set()
    for item in changes:
        if not isinstance(item, dict):
            raise ValueError("Every correction must be an object.")
        candidate_id, name = item.get("id"), item.get("name")
        if not isinstance(candidate_id, str) or not re.fullmatch(r"[a-z0-9-]{1,64}", candidate_id):
            raise ValueError("A correction needs an exact candidate ID.")
        if candidate_id in seen:
            raise ValueError("Each queued candidate may be corrected only once per batch.")
        seen.add(candidate_id)
        row = conn.execute(
            "SELECT state,candidate,result,verification FROM automatic_map_entries WHERE id=?", (candidate_id,)
        ).fetchone()
        if row is None or row[0] != "ready":
            raise ValueError(f"{candidate_id} is not an unpublished ready candidate.")
        candidate, result, verification = (json.loads(value) for value in row[1:])
        if candidate.get("canonical_name") != name:
            raise ValueError(f"{candidate_id} no longer matches the expected name.")
        current_hash = discovery.digest({"candidate": candidate, "result": result})
        if (not isinstance(item.get("expected_payload_sha256"), str)
                or item["expected_payload_sha256"] != current_hash
                or verification.get("payload_sha256") != current_hash):
            raise ValueError(f"{candidate_id} no longer matches the reviewed payload hash.")
        reason = item.get("reason")
        if not isinstance(reason, str) or not 12 <= len(reason.strip()) <= 300:
            raise ValueError("Give each correction a specific 12–300 character reason.")
        edits = item.get("edits")
        if not isinstance(edits, dict) or not edits or set(edits) - set(controlled.LEVELS):
            raise ValueError("Only hard, medium, and easy clue wording may be corrected.")
        revised = json.loads(json.dumps(candidate))
        audit = {}
        for level, edit in edits.items():
            if not isinstance(edit, dict) or set(edit) != {"old", "new", "source_url", "evidence_quote"}:
                raise ValueError("Each edit needs old/new text, a source URL, and an evidence quote.")
            old, new, quote, url = (edit[key] for key in ("old", "new", "evidence_quote", "source_url"))
            if not all(isinstance(value, str) for value in (old, new, quote, url)):
                raise ValueError("Correction fields must be strings.")
            if (result["clue_ladder"].get(level) != old
                    or candidate["facts"][level].get("text") != old or old == new):
                raise ValueError(f"{candidate_id} {level} no longer matches the reviewed clue.")
            if not 12 <= len(quote.strip()) <= 500 or any(char in quote for char in "<>\r\n"):
                raise ValueError("Supply a concise, single-line source quotation.")
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Editorial evidence must have a public HTTPS source URL.")
            source_id = f"editorial_{level}"
            revised["sources"][source_id] = url
            revised["facts"][level].update(text=new, source_ids=[source_id],
                                             supporting_quote=quote, supporting_quotes=[quote])
            audit[level] = {"old": old, "new": new, "source_url": url, "evidence_quote": quote}
        payload = {"place_id": candidate_id, "selection_reason": result["selection_reason"],
                   "clues": {level: {"text": revised["facts"][level]["text"], "fact_id": level}
                             for level in controlled.LEVELS}}
        validated = controlled.validate_result(payload, [revised])
        if not validated["automated_pass"]:
            raise ValueError(f"{candidate_id} fails Map clue validation: {validated['validation']['failure_reasons']}")
        prepared.append({"id": candidate_id, "name": name, "candidate": revised, "result": validated,
                         "verification": verification, "reason": reason.strip(), "audit": audit})
    return prepared


def correct(database: Path, changes: list[dict], *, apply: bool = False,
            backup_root: Path | None = None) -> dict[str, Any]:
    if not database.is_file() or database.is_symlink():
        raise ValueError("The database must be an existing, regular file.")
    with closing(sqlite3.connect(database, timeout=10)) as conn:
        prepared = checked_changes(conn, changes)
    summary = [{"id": item["id"], "name": item["name"], "levels": list(item["audit"])}
               for item in prepared]
    if not apply:
        return {"status": "dry_run", "entries": summary}
    if backup_root is None:
        raise ValueError("An explicit backup root is required for an applied correction.")
    backup = backup_manager.create_backup(database.parent, backup_root, database_name=database.name)
    backup_manager.verify_backup(backup)
    corrected_at = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(database, timeout=10)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        prepared = checked_changes(conn, changes)
        for item in prepared:
            verification = item["verification"]
            verification["operator_correction"] = {
                "reason": item["reason"], "at": corrected_at, "edits": item["audit"]}
            verification["payload_sha256"] = discovery.digest({
                "candidate": item["candidate"], "result": item["result"]})
            changed = conn.execute(
                "UPDATE automatic_map_entries SET candidate=?,result=?,verification=? "
                "WHERE id=? AND state='ready'",
                (json.dumps(item["candidate"], ensure_ascii=False),
                 json.dumps(item["result"], ensure_ascii=False),
                 json.dumps(verification, ensure_ascii=False), item["id"]),
            )
            if changed.rowcount != 1:
                raise RuntimeError("A queued place changed during correction; no changes were committed.")
        conn.commit()
    return {"status": "applied", "entries": summary, "backup": str(backup)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--changes", type=Path, required=True, help="Private JSON file with an entries array")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-root", type=Path)
    args = parser.parse_args()
    try:
        document = json.loads(args.changes.read_text(encoding="utf-8"))
        result = correct(args.database, document["entries"], apply=args.apply,
                         backup_root=args.backup_root)
    except (ValueError, RuntimeError, OSError, KeyError, TypeError, sqlite3.Error,
            backup_manager.BackupError) as error:
        parser.exit(1, f"Map queue correction failed: {error}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

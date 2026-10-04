"""Dry-run or retire exact unpublished Map candidates after an editorial review.

Retirement is reversible: no candidate, published round, or player data is
deleted. An online database backup is verified before any queue state changes.
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

from deploy import backup_manager


def parse_targets(values: list[str]) -> dict[str, str]:
    targets: dict[str, str] = {}
    for value in values:
        candidate_id, separator, name = value.partition("=")
        if not separator or not re.fullmatch(r"[a-z0-9-]{1,64}", candidate_id) or not name.strip():
            raise ValueError("Each target must be ID=exact canonical name.")
        if candidate_id in targets:
            raise ValueError("Each candidate ID may be named only once.")
        targets[candidate_id] = name.strip()
    if not targets:
        raise ValueError("Name at least one unpublished candidate.")
    return targets


def checked_entries(conn: sqlite3.Connection, targets: dict[str, str]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for candidate_id, expected_name in targets.items():
        row = conn.execute(
            "SELECT state, candidate FROM automatic_map_entries WHERE id = ?", (candidate_id,)
        ).fetchone()
        if row is None or row[0] != "ready":
            raise ValueError(f"{candidate_id} is not an unpublished ready candidate.")
        candidate = json.loads(row[1])
        if not isinstance(candidate, dict) or candidate.get("canonical_name") != expected_name:
            raise ValueError(f"{candidate_id} no longer matches the expected place name.")
        entries.append({"id": candidate_id, "name": expected_name})
    return entries


def review(
    database: Path,
    targets: dict[str, str],
    *,
    reason: str,
    apply: bool = False,
    backup_root: Path | None = None,
) -> dict[str, Any]:
    reason = " ".join(reason.split())
    if not 12 <= len(reason) <= 300:
        raise ValueError("Provide a specific editorial reason of 12–300 characters.")
    if not database.is_file() or database.is_symlink():
        raise ValueError("The database must be an existing, regular file.")
    with closing(sqlite3.connect(database, timeout=10)) as conn:
        entries = checked_entries(conn, targets)
    if not apply:
        return {"status": "dry_run", "entries": entries}
    if backup_root is None:
        raise ValueError("An explicit backup root is required for an applied review.")
    backup = backup_manager.create_backup(database.parent, backup_root, database_name=database.name)
    backup_manager.verify_backup(backup)
    reviewed_at = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(database, timeout=10)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        entries = checked_entries(conn, targets)
        for entry in entries:
            row = conn.execute(
                "SELECT verification FROM automatic_map_entries WHERE id = ?", (entry["id"],)
            ).fetchone()
            verification = json.loads(row[0])
            if not isinstance(verification, dict):
                raise ValueError("The queue verification record is invalid.")
            verification["operator_rejection"] = {"reason": reason, "at": reviewed_at}
            changed = conn.execute(
                "UPDATE automatic_map_entries SET state = 'rejected', verification = ? "
                "WHERE id = ? AND state = 'ready'",
                (json.dumps(verification, sort_keys=True), entry["id"]),
            )
            if changed.rowcount != 1:
                raise RuntimeError("A queued place changed during review; no changes were committed.")
        conn.commit()
    return {"status": "applied", "entries": entries, "backup": str(backup)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--target", action="append", default=[], help="ID=exact canonical name; repeatable")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--apply", action="store_true", help="Retire only after a verified online backup")
    parser.add_argument("--backup-root", type=Path)
    args = parser.parse_args()
    try:
        result = review(
            args.database,
            parse_targets(args.target),
            reason=args.reason,
            apply=args.apply,
            backup_root=args.backup_root,
        )
    except (ValueError, RuntimeError, OSError, sqlite3.Error, backup_manager.BackupError) as error:
        parser.exit(1, f"Map queue review failed: {error}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import daily_quiz
from tools import build_quiz_learning_profile

DEFAULT_DB_PATH = PROJECT_DIR / "data" / "fultons.db"
DEFAULT_TRAINING_DIR = PROJECT_DIR / "data" / "training"
RUNTIME_PROFILE_VERSION = 2


def connect_database(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def latest_negative_files(training_dir: Path) -> list[Path]:
    matches = sorted(
        training_dir.glob("football_review_negative_*.jsonl"),
        key=lambda path: (path.stat().st_mtime, path.name),
    )
    return matches[-1:] if matches else []


def feedback_entries_from_attempt(row: sqlite3.Row) -> list[str]:
    entries: list[str] = []
    reason = str(row["failure_reason"] or "").strip()
    if reason and not daily_quiz.is_transient_provider_failure(reason):
        entries.append(reason)
    critic_json = row["critic_json"]
    if critic_json:
        try:
            critic = json.loads(critic_json)
        except json.JSONDecodeError:
            critic = None
        if isinstance(critic, dict):
            feedback = str(critic.get("feedback_to_generator") or "").strip()
            if feedback:
                entries.append(feedback)
            for reason in critic.get("failure_reasons") or []:
                text = str(reason or "").strip()
                if text:
                    entries.append(text)
    return entries


def failed_attempt_records(
    conn: sqlite3.Connection,
    *,
    since_date: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = "WHERE passed = 0"
    if since_date:
        where += " AND quiz_date >= ?"
        params.append(since_date)
    params.append(max(1, limit))
    rows = conn.execute(
        f"""
        SELECT quiz_date, subject, difficulty, failure_reason, critic_json, provider
        FROM daily_quiz_attempts
        {where}
        ORDER BY id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()

    records: list[dict[str, Any]] = []
    for row in rows:
        if daily_quiz.is_transient_provider_failure(str(row["failure_reason"] or "")):
            continue
        feedback: list[str] = []
        seen: set[str] = set()
        for entry in feedback_entries_from_attempt(row):
            normalized = daily_quiz.normalize_text(entry)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            feedback.append(entry)
        if feedback:
            records.append(
                {
                    "feedback_to_generator": "; ".join(feedback)[:2400],
                    "metadata": {
                        "reason": "daily_quiz_attempt_failure",
                        "quiz_date": row["quiz_date"],
                        "subject": row["subject"],
                        "difficulty": row["difficulty"],
                        "provider": row["provider"],
                    },
                }
            )
    return records


def read_negative_records(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        records.extend(build_quiz_learning_profile.read_jsonl(path))
    return records


def candidate_policy_from_database(conn: sqlite3.Connection) -> dict[str, Any]:
    try:
        rows = conn.execute(
            """
            SELECT subject, difficulty, topic_lane, provider, status,
                   rejection_stage, failure_reason
            FROM daily_quiz_candidates
            WHERE status IN ('accepted', 'rejected')
            ORDER BY id DESC LIMIT 5000
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    by_slot: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_slot[f"{row['subject']}/{row['difficulty']}"].append(row)
    policy: dict[str, Any] = {}
    for slot, slot_rows in by_slot.items():
        lane_totals: Counter[str] = Counter()
        lane_passes: Counter[str] = Counter()
        provider_totals: Counter[str] = Counter()
        provider_passes: Counter[str] = Counter()
        failures: Counter[str] = Counter()
        for row in slot_rows:
            lane = str(row["topic_lane"] or "unknown")
            provider = str(row["provider"] or "unknown")
            passed = row["status"] == "accepted"
            lane_totals[lane] += 1
            provider_totals[provider] += 1
            lane_passes[lane] += int(passed)
            provider_passes[provider] += int(passed)
            if not passed:
                failures[str(row["rejection_stage"] or "unknown")] += 1
        policy[slot] = {
            "sample_count": len(slot_rows),
            "lane_weights": {
                lane: round((lane_passes[lane] + 1) / (total + 2), 4)
                for lane, total in sorted(lane_totals.items())
            },
            "provider_weights": {
                provider: round((provider_passes[provider] + 1) / (total + 2), 4)
                for provider, total in sorted(provider_totals.items())
            },
            "failure_categories": dict(failures.most_common()),
        }
    return policy


def validate_profile(profile: dict[str, Any], *, max_feedback: int = 8, max_length: int = 240) -> list[str]:
    errors: list[str] = []
    by_slot = profile.get("feedback_by_slot")
    if not isinstance(by_slot, dict) or not by_slot:
        errors.append("feedback_by_slot must be a non-empty object.")
        return errors
    for slot, feedback in by_slot.items():
        if not isinstance(slot, str) or "/" not in slot:
            errors.append(f"Invalid slot key: {slot!r}.")
        if not isinstance(feedback, list) or not feedback:
            errors.append(f"{slot} must contain at least one feedback entry.")
            continue
        if len(feedback) > max_feedback:
            errors.append(f"{slot} has {len(feedback)} entries; maximum is {max_feedback}.")
        seen: set[str] = set()
        for item in feedback:
            text = str(item or "").strip()
            normalized = daily_quiz.normalize_text(text)
            if not text:
                errors.append(f"{slot} contains blank feedback.")
            if len(text) > max_length:
                errors.append(f"{slot} contains feedback longer than {max_length} characters.")
            if normalized in seen:
                errors.append(f"{slot} contains duplicate feedback: {text!r}.")
            seen.add(normalized)
    candidate_policy = profile.get("candidate_policy_by_slot", {})
    if not isinstance(candidate_policy, dict):
        errors.append("candidate_policy_by_slot must be an object when present.")
    else:
        for slot, values in candidate_policy.items():
            if not isinstance(values, dict):
                errors.append(f"Candidate policy {slot!r} must be an object.")
                continue
            for key in ("lane_weights", "provider_weights"):
                weights = values.get(key, {})
                if not isinstance(weights, dict) or any(
                    not isinstance(weight, (int, float)) or not 0 <= weight <= 1
                    for weight in weights.values()
                ):
                    errors.append(f"Candidate policy {slot!r} has invalid {key}.")
    return errors


def build_candidate_profile(
    conn: sqlite3.Connection,
    *,
    negative_files: list[Path],
    since_date: str | None = None,
    attempt_limit: int = 500,
) -> dict[str, Any]:
    negative_records = read_negative_records(negative_files)
    attempt_records = failed_attempt_records(conn, since_date=since_date, limit=attempt_limit)
    if not negative_records and not attempt_records:
        raise ValueError("No negative review records or failed attempts found for profile refresh.")
    profile = build_quiz_learning_profile.build_profile(
        [*negative_records, *attempt_records],
        source=Path("combined_negative_review_and_failed_attempts"),
    )
    profile["source_negative_files"] = [str(path) for path in negative_files]
    profile["failed_attempt_record_count"] = len(attempt_records)
    profile["refresh_since_date"] = since_date
    profile["refresh_attempt_limit"] = attempt_limit
    profile["candidate_policy_by_slot"] = candidate_policy_from_database(conn)
    errors = validate_profile(profile)
    profile["validation"] = {"passed": not errors, "errors": errors}
    return profile


def write_candidate_profile(
    profile: dict[str, Any],
    output_dir: Path,
    *,
    prefix: str = "quiz_learning_profile_candidate",
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"{prefix}_{timestamp}.json"
    output_path.write_text(json.dumps(profile, indent=2, ensure_ascii=True), encoding="utf-8")
    return output_path


def refresh_runtime_profile(conn: sqlite3.Connection, profile_path: str) -> dict[str, Any]:
    """Atomically update the configured profile from live, rejected attempts.

    Only deterministic, template-based lessons are promoted into prompts. The
    existing reviewed wildcard guidance remains in place, and invalid refreshes
    leave the previous profile untouched.
    """
    if not profile_path:
        return {"status": "disabled"}
    path = Path(profile_path)
    if path.is_symlink():
        raise ValueError("Quiz learning profile must not be a symbolic link.")
    previous = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if not isinstance(previous, dict):
        raise ValueError("Existing quiz learning profile is not an object.")
    progress = {
        "attempt_id": int(conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM daily_quiz_attempts WHERE passed=0"
        ).fetchone()[0]),
        "candidate_id": int(conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM daily_quiz_candidates"
        ).fetchone()[0]),
    }
    if (previous.get("runtime_source_progress") == progress
            and previous.get("runtime_profile_version") == RUNTIME_PROFILE_VERSION):
        return {"status": "unchanged", **progress}
    if progress["attempt_id"] == 0:
        return {"status": "no_feedback", **progress}

    profile = build_candidate_profile(conn, negative_files=[], attempt_limit=500)
    old_feedback = previous.get("feedback_by_slot", {})
    if isinstance(old_feedback, dict):
        for slot, values in old_feedback.items():
            if not isinstance(slot, str) or not slot.endswith("/*") or not isinstance(values, list):
                continue
            reviewed = [
                value.strip() for value in values
                if isinstance(value, str) and 0 < len(value.strip()) <= 240
            ]
            profile["feedback_by_slot"][slot] = daily_quiz.merge_feedback_entries(
                reviewed, profile["feedback_by_slot"].get(slot, []), limit=8
            )
    errors = validate_profile(profile)
    if errors:
        raise ValueError("Invalid live quiz learning profile: " + "; ".join(errors[:3]))
    profile["runtime_source_progress"] = progress
    profile["runtime_profile_version"] = RUNTIME_PROFILE_VERSION
    profile["validation"] = {"passed": True, "errors": []}

    # A same-directory replacement keeps readers on either complete version.
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(profile, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return {"status": "updated", **progress, "slots": len(profile["feedback_by_slot"])}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and validate a candidate quiz learning profile from reviewed negatives and recent failed attempts.",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--training-dir", type=Path, default=DEFAULT_TRAINING_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_TRAINING_DIR)
    parser.add_argument("--negative-file", type=Path, action="append", default=[])
    parser.add_argument("--since-date")
    parser.add_argument("--attempt-limit", type=int, default=500)
    parser.add_argument("--prefix", default="quiz_learning_profile_candidate")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"Database not found: {args.db}")
    negative_files = args.negative_file or latest_negative_files(args.training_dir)
    conn = connect_database(args.db)
    try:
        profile = build_candidate_profile(
            conn,
            negative_files=negative_files,
            since_date=args.since_date,
            attempt_limit=args.attempt_limit,
        )
    finally:
        conn.close()
    output_path = write_candidate_profile(profile, args.out_dir, prefix=args.prefix)
    print(
        json.dumps(
            {
                "profile_path": str(output_path),
                "validation": profile["validation"],
                "negative_count": profile["negative_count"],
                "failed_attempt_record_count": profile["failed_attempt_record_count"],
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0 if profile["validation"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

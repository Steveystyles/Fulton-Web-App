from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TRAINING_DIR = PROJECT_DIR / "data" / "training"


PATTERNS = (
    (
        "underspecified_multi_answer",
        re.compile(r"under-specified|more than once|possible valid answers", re.IGNORECASE),
        "Avoid under-specified football questions where one player, team, or event can produce multiple valid answers; add the exact goal/event or choose a different hook.",
    ),
    (
        "arbitrary_dated_fixture",
        re.compile(r"date-based|dated fixture|ordinary score|not inherently memorable", re.IGNORECASE),
        "Avoid arbitrary dated fixture recall and ordinary match-score questions unless the match has clear historical significance.",
    ),
    (
        "difficulty_miscalibrated",
        re.compile(r"easy rating is poorly calibrated|more appropriate than easy", re.IGNORECASE),
        "Do not label specialist venue, minute, score, or narrow fixture recall as easy; escalate it or replace it with a broader football hook.",
    ),
    (
        "minute_specific",
        re.compile(r"\bminute\b|extremely specific", re.IGNORECASE),
        "Avoid minute-by-minute scorer trivia unless the question uniquely identifies a decisive, memorable moment.",
    ),
    (
        "needs_verification",
        re.compile(r"needs? .*verification|answer appears wrong|incorrect", re.IGNORECASE),
        "Prefer questions with a clear verification source and one answer that exactly matches one of the choices.",
    ),
)

POSITIVE_GUIDANCE = (
    "Prefer stable, source-backed football history, tournament structure, season-level achievements, decisive shootouts, awards, and memorable competition facts.",
    "Use plausible same-domain distractors: clubs from the same league, teams from the same tournament, or numbers close to the verified answer.",
)


def latest_negative_file(training_dir: Path) -> Path:
    matches = sorted(
        training_dir.glob("football_review_negative_*.jsonl"),
        key=lambda path: (path.stat().st_mtime, path.name),
    )
    if not matches:
        raise ValueError(f"No football_review_negative_*.jsonl files found in {training_dir}.")
    return matches[-1]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            record = json.loads(stripped)
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number} is not a JSON object.")
            records.append(record)
    return records


def build_profile(records: list[dict[str, Any]], *, source: Path) -> dict[str, Any]:
    pattern_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()

    for record in records:
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        status = str(metadata.get("reason") or metadata.get("status") or "unknown")
        status_counts[status] += 1
        feedback = str(record.get("feedback_to_generator") or record.get("failure_reason") or "")
        if feedback:
            reason_counts[feedback] += 1
        for key, pattern, _guidance in PATTERNS:
            if pattern.search(feedback):
                pattern_counts[key] += 1

    feedback = list(POSITIVE_GUIDANCE)
    for key, _pattern, guidance in PATTERNS:
        count = pattern_counts[key]
        if count:
            feedback.append(f"{guidance} Seen in {count} reviewed negative examples.")

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_negative_file": str(source),
        "negative_count": len(records),
        "feedback_by_slot": {
            "football/*": feedback[:8],
        },
        "pattern_counts": dict(pattern_counts),
        "negative_reason_counts": dict(status_counts),
        "top_feedback": [
            {"feedback": text, "count": count}
            for text, count in reason_counts.most_common(10)
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a compact quiz learning profile from reviewed negative examples.",
    )
    parser.add_argument("--negative-file", type=Path)
    parser.add_argument("--training-dir", type=Path, default=DEFAULT_TRAINING_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_TRAINING_DIR)
    parser.add_argument("--prefix", default="quiz_learning_profile")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    negative_file = args.negative_file or latest_negative_file(args.training_dir)
    records = read_jsonl(negative_file)
    profile = build_profile(records, source=negative_file)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = args.out_dir / f"{args.prefix}_{stamp}.json"
    output_path.write_text(json.dumps(profile, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"profile_path": str(output_path), **profile}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

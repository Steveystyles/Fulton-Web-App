from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import daily_map_game
from tools import build_map_learning_profile, map_clue_failure_log, training_data_store

DEFAULT_TRAINING_DIR = PROJECT_DIR / "data" / "training"
DEFAULT_GOLD_EXAMPLES_PATH = DEFAULT_TRAINING_DIR / "map_clue_gold_examples.json"


def latest_negative_files(training_dir: Path) -> list[Path]:
    matches = sorted(
        training_dir.glob("map_clue_negative_*.jsonl"),
        key=lambda path: (path.stat().st_mtime, path.name),
    )
    return matches[-1:] if matches else []


def latest_failure_log_files(training_dir: Path) -> list[Path]:
    candidates = [training_dir / "map_clue_failure_log.jsonl"]
    candidates.extend(
        sorted(
            training_dir.glob("map_clue_failure_log_*.jsonl"),
            key=lambda path: (path.stat().st_mtime, path.name),
        )
    )
    return [path for path in candidates if path.exists()]


def latest_review_rows_files(training_dir: Path) -> list[Path]:
    matches = sorted(
        training_dir.glob("map_clue_review_rows_*.jsonl"),
        key=lambda path: (path.stat().st_mtime, path.name),
    )
    return matches[-1:] if matches else []


def read_negative_records(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        records.extend(build_map_learning_profile.read_jsonl(path))
    return records


def read_failure_records(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        records.extend(map_clue_failure_log.read_failure_log(path))
    return records


def place_review_failure_records(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in training_data_store.read_map_place_review_feedback_rows(paths):
        place = str(row.get("place") or row.get("canonical_name") or "").strip()
        place_type = str(row.get("type") or row.get("place_type") or "*").strip() or "*"
        clues = row.get("clues") if isinstance(row.get("clues"), dict) else {}
        reviews = row.get("clue_reviews") if isinstance(row.get("clue_reviews"), dict) else {}
        clue_scores = row.get("clue_scores") if isinstance(row.get("clue_scores"), dict) else {}
        source_file = str(row.get("_source_file") or "")

        for level in ("hard", "medium", "easy"):
            review = reviews.get(level) if isinstance(reviews.get(level), dict) else {}
            verdict = str(
                review.get("pass_fail")
                or review.get("passFail")
                or clue_scores.get(level)
                or ""
            ).strip().casefold()
            if verdict != "fail":
                if verdict == "pass" and qualified_pass_reason(
                    str(review.get("reason") or "")
                ):
                    reason = str(review.get("reason") or "").strip()
                    clue = str(review.get("clue") or clues.get(level) or "").strip()
                    categories = qualified_pass_categories(level, reason, clue)
                    records.append(
                        {
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "run_id": source_file,
                            "report_path": source_file,
                            "place_id": row.get("candidate_id"),
                            "place": place,
                            "place_type": place_type,
                            "difficulty": level,
                            "status": "human_qualified_pass",
                            "generated": {level: clue},
                            "failure_reason": reason,
                            "failure_reasons": [reason],
                            "failure_categories": categories,
                            "feedback_to_generator": human_review_feedback(level, reason),
                            "critic_source": "human",
                            "metadata": {
                                "reason": "map_place_review_qualified_pass",
                                "failure_categories": categories,
                                "place": place,
                                "place_type": place_type,
                                "difficulty": level,
                                "critic_source": "human",
                            },
                        }
                    )
                continue
            clue = str(review.get("clue") or clues.get(level) or "").strip()
            reason = str(review.get("reason") or f"Human reviewer failed the {level} clue.").strip()
            categories = map_clue_failure_log.classify_failure_reasons([reason, clue])
            required_category = {
                "hard": "weak_hard_hook",
                "medium": "weak_medium_narrowing",
                "easy": "weak_easy_map_anchor",
            }[level]
            categories = [required_category, *categories]
            if level == "hard":
                categories.append("insufficient_event_detail")
                categories.append("non_specific_incident")
                if daily_static_hook_text(clue):
                    categories.append("engineered_hard_hook")
            categories = list(dict.fromkeys(categories))
            records.append(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "run_id": source_file,
                    "report_path": source_file,
                    "place_id": row.get("candidate_id"),
                    "place": place,
                    "place_type": place_type,
                    "difficulty": level,
                    "status": "human_rejected",
                    "generated": {level: clue},
                    "failure_reason": reason,
                    "failure_reasons": [reason],
                    "failure_categories": categories,
                    "feedback_to_generator": human_review_feedback(level, reason),
                    "critic_source": "human",
                    "metadata": {
                        "reason": "map_place_review_failure",
                        "failure_categories": categories,
                        "place": place,
                        "place_type": place_type,
                        "difficulty": level,
                        "critic_source": "human",
                    },
                }
            )

        overall = row.get("overall_review") if isinstance(row.get("overall_review"), dict) else {}
        overall_verdict = str(
            overall.get("pass_fail") or overall.get("passFail") or row.get("your_score") or ""
        ).strip().casefold()
        if overall_verdict == "fail":
            reason = str(overall.get("reason") or row.get("notes") or "").strip()
            categories = ["place_selected_before_hook", "weak_hard_hook"]
            records.append(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "run_id": source_file,
                    "report_path": source_file,
                    "place_id": row.get("candidate_id"),
                    "place": place,
                    "place_type": place_type,
                    "difficulty": "*",
                    "status": "human_rejected",
                    "generated": clues,
                    "failure_reason": reason,
                    "failure_reasons": [reason],
                    "failure_categories": categories,
                    "feedback_to_generator": [
                        "Find a verified, unique event or incident first; only then use its location as the round target.",
                        "Reject the candidate entirely when no qualifying hard hook exists.",
                    ],
                    "critic_source": "human",
                    "metadata": {
                        "reason": "map_place_review_overall_failure",
                        "failure_categories": categories,
                        "place": place,
                        "place_type": place_type,
                        "difficulty": "*",
                        "critic_source": "human",
                    },
                }
            )
    return records


def daily_static_hook_text(clue: str) -> bool:
    return bool(
        re.search(
            r"\b(?:architect|architecture|designed by|construction|built by|"
            r"appearance|facade|roof|dimensions?|capacity)\b",
            clue,
            re.IGNORECASE,
        )
    )


def qualified_pass_reason(reason: str) -> bool:
    normalized = str(reason or "").strip().casefold()
    return bool(
        normalized
        and any(
            token in normalized
            for token in (
                "still",
                " but ",
                "not ",
                "doesn't",
                "does not",
                "feels",
                "bland",
                "weak",
                "missing",
                "unclear",
                "vague",
                "unhelpful",
                "could",
                "should",
                "incomplete",
            )
        )
    )


def qualified_pass_categories(level: str, reason: str, clue: str) -> list[str]:
    if level == "hard":
        return ["insufficient_event_detail", "missing_place_link"]
    if level == "easy":
        return ["weak_easy_map_anchor"]
    categories = ["weak_medium_narrowing"]
    combined = f"{reason} {clue}"
    if daily_map_game.MAP_MEDIUM_FILLER_RE.search(combined):
        categories.append("medium_filler")
    if daily_map_game.medium_uses_unnamed_cultural_reference(combined):
        categories.append("unnamed_cultural_reference")
    if (
        "fiction" in reason.casefold()
        or "real fact" in reason.casefold()
        or daily_map_game.medium_blurs_fiction_and_history(clue)
    ):
        categories.append("fictional_context_ambiguity")
    return categories


def human_review_feedback(level: str, reason: str) -> list[str]:
    if level == "hard":
        return [
            "Select one verified recognition hook before selecting the place; prefer a unique incident or story but allow another genuinely distinctive place-owned hook.",
            "Retain the people, action, outcome, consequence, record, or significance that makes the hook recognisable, and link it to the target without geographic hints.",
            f"Human review: {reason}",
        ]
    if level == "medium":
        return [
            "Materially reduce the geographic search area; a second interesting fact is useful only when it also advances that narrowing.",
            "Name an answer-safe creator, person, group, or work instead of using a vague famous or well-known label; if a title leaks the target, name its creator and explain the connection.",
            "Clearly label fictional or imaginary characters and events as fiction instead of presenting them as historical people.",
            f"Human review: {reason}",
        ]
    return [
        "Narrow within medium's area to a visible borough, district, quarter, neighbourhood, city sector, river crossing, park, station, or named local landmark.",
        f"Human reviewer failed the {level} clue: {reason}",
    ]


def read_gold_examples(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    examples = payload.get("examples") if isinstance(payload, dict) else None
    if not isinstance(examples, list):
        raise ValueError(f"{path} must contain an examples array.")
    return [dict(example) for example in examples if isinstance(example, dict)]


def clean_human_approved_examples_from_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    approved_by_place: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not training_data_store.map_place_review_is_clean_approval(row):
            continue
        place = str(row.get("place") or row.get("canonical_name") or "").strip()
        clues = row.get("clues") if isinstance(row.get("clues"), dict) else {}
        if not place or not all(str(clues.get(level) or "").strip() for level in ("hard", "medium", "easy")):
            continue
        place_key = place.casefold()
        approved_by_place[place_key] = {
            "example_id": f"human-approved-{row.get('candidate_id') or place_key.replace(' ', '-')}",
            "status": "human_approved",
            "source": str(row.get("_source_file") or ""),
            "audience": "adult player; the owner's father",
            "place": place,
            "place_type": str(row.get("type") or row.get("place_type") or "place"),
            "place_selection": {
                "why_it_passed": "The human reviewer passed the place choice without qualification."
            },
            "clue_ladder": {
                level: str(clues.get(level) or "").strip()
                for level in ("hard", "medium", "easy")
            },
            "why_the_ladder_passed": (
                "The human reviewer passed hard, medium, and easy without qualification."
            ),
            "generalisation_note": (
                "Learn the level roles and solving value from this result; do not copy its subject or wording."
            ),
        }
    return list(approved_by_place.values())


def clean_human_approved_examples(paths: list[Path]) -> list[dict[str, Any]]:
    return clean_human_approved_examples_from_rows(
        training_data_store.read_map_place_review_feedback_rows(paths)
    )


def merge_approved_examples(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for examples in groups:
        for example in examples:
            place = str(example.get("place") or example.get("example_id") or "").strip().casefold()
            if place:
                merged[place] = dict(example)
    return list(merged.values())


def validate_profile(profile: dict[str, Any], *, max_feedback: int = 8, max_length: int = 260) -> list[str]:
    errors: list[str] = []
    by_slot = profile.get("feedback_by_slot")
    if not isinstance(by_slot, dict) or not by_slot:
        errors.append("feedback_by_slot must be a non-empty object.")
        return errors
    for slot, feedback in by_slot.items():
        if not isinstance(slot, str) or (slot != "global" and "/" not in slot):
            errors.append(f"Invalid slot key: {slot!r}.")
        if not isinstance(feedback, list) or not feedback:
            errors.append(f"{slot} must contain at least one feedback entry.")
            continue
        if len(feedback) > max_feedback:
            errors.append(f"{slot} has {len(feedback)} entries; maximum is {max_feedback}.")
        seen: set[str] = set()
        for item in feedback:
            text = str(item or "").strip()
            normalized = re.sub(r"\s+", " ", text).casefold()
            if not text:
                errors.append(f"{slot} contains blank feedback.")
            if len(text) > max_length:
                errors.append(f"{slot} contains feedback longer than {max_length} characters.")
            if normalized in seen:
                errors.append(f"{slot} contains duplicate feedback: {text!r}.")
            seen.add(normalized)
    return errors


def build_candidate_profile(
    *,
    negative_files: list[Path],
    failure_log_files: list[Path] | None = None,
    review_rows_files: list[Path] | None = None,
    place_review_feedback_files: list[Path] | None = None,
    gold_examples_file: Path | None = DEFAULT_GOLD_EXAMPLES_PATH,
) -> dict[str, Any]:
    failure_log_files = failure_log_files or []
    review_rows_files = review_rows_files or []
    place_review_feedback_files = place_review_feedback_files or []
    negative_records = read_negative_records(negative_files)
    failure_records = read_failure_records(failure_log_files)
    human_failure_records = place_review_failure_records(place_review_feedback_files)
    review_records = read_negative_records(review_rows_files)
    gold_examples = read_gold_examples(gold_examples_file)
    human_approved_examples = clean_human_approved_examples(place_review_feedback_files)
    records = [*negative_records, *failure_records, *human_failure_records]
    if not records:
        raise ValueError("No negative map clue or failure-log records found for profile refresh.")
    profile = build_map_learning_profile.build_profile(
        records,
        source=Path("combined_map_clue_negative_and_failure_records"),
    )
    profile["source_negative_files"] = [str(path) for path in negative_files]
    profile["source_failure_log_files"] = [str(path) for path in failure_log_files]
    profile["source_review_rows_files"] = [str(path) for path in review_rows_files]
    profile["source_place_review_feedback_files"] = [
        str(path) for path in place_review_feedback_files
    ]
    profile["negative_record_count"] = len(negative_records)
    profile["failure_log_record_count"] = len(failure_records)
    profile["human_failure_record_count"] = len(human_failure_records)
    profile["review_record_count"] = len(review_records)
    profile["approved_examples_by_level"] = build_map_learning_profile.approved_examples_by_level(
        review_records,
    )
    profile["approved_ladders"] = merge_approved_examples(
        gold_examples,
        human_approved_examples,
    )
    profile["human_approved_ladder_count"] = len(human_approved_examples)
    profile["source_gold_examples_file"] = (
        str(gold_examples_file) if gold_examples_file is not None else ""
    )
    profile["generator_env_var"] = "MAP_LEARNING_PROFILE_PATH"
    profile["generator_consumers"] = ["daily_map_game.generate_reviewed_clue_ladder"]
    errors = validate_profile(profile)
    profile["validation"] = {"passed": not errors, "errors": errors}
    return profile


def write_candidate_profile(
    profile: dict[str, Any],
    output_dir: Path,
    *,
    prefix: str = "map_learning_profile_candidate",
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"{prefix}_{timestamp}.json"
    output_path.write_text(json.dumps(profile, indent=2, ensure_ascii=True), encoding="utf-8")
    validation = profile.get("validation") if isinstance(profile.get("validation"), dict) else {}
    if validation.get("passed", True):
        latest_path = output_dir / "map_learning_profile_latest.json"
        latest_path.write_text(json.dumps(profile, indent=2, ensure_ascii=True), encoding="utf-8")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and validate a candidate map clue learning profile from negative review examples.",
    )
    parser.add_argument("--training-dir", type=Path, default=DEFAULT_TRAINING_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_TRAINING_DIR)
    parser.add_argument("--negative-file", type=Path, action="append", default=[])
    parser.add_argument(
        "--no-negative-file",
        action="store_true",
        help="Build the profile without exported negative JSONL files.",
    )
    parser.add_argument("--failure-log-file", type=Path, action="append", default=[])
    parser.add_argument("--review-rows-file", type=Path, action="append", default=[])
    parser.add_argument("--place-review-feedback-file", type=Path, action="append", default=[])
    parser.add_argument("--gold-examples-file", type=Path, default=DEFAULT_GOLD_EXAMPLES_PATH)
    parser.add_argument(
        "--no-review-rows",
        action="store_true",
        help="Build the profile without approved clue demonstrations.",
    )
    parser.add_argument(
        "--no-failure-log",
        action="store_true",
        help="Build the profile from negative JSONL files only.",
    )
    parser.add_argument(
        "--no-place-review-feedback",
        action="store_true",
        help="Build the profile without human map place/clue review feedback.",
    )
    parser.add_argument("--prefix", default="map_learning_profile_candidate")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    negative_files = [] if args.no_negative_file else (args.negative_file or latest_negative_files(args.training_dir))
    failure_log_files = [] if args.no_failure_log else (args.failure_log_file or latest_failure_log_files(args.training_dir))
    review_rows_files = [] if args.no_review_rows else (args.review_rows_file or latest_review_rows_files(args.training_dir))
    place_review_feedback_files = (
        []
        if args.no_place_review_feedback
        else (
            args.place_review_feedback_file
            or training_data_store.default_map_place_review_feedback_files(args.training_dir)
        )
    )
    profile = build_candidate_profile(
        negative_files=negative_files,
        failure_log_files=failure_log_files,
        review_rows_files=review_rows_files,
        place_review_feedback_files=place_review_feedback_files,
        gold_examples_file=args.gold_examples_file,
    )
    output_path = write_candidate_profile(profile, args.out_dir, prefix=args.prefix)
    print(
        json.dumps(
            {
                "profile_path": str(output_path),
                "validation": profile["validation"],
                "negative_count": profile["negative_count"],
                "negative_record_count": profile["negative_record_count"],
                "failure_log_record_count": profile["failure_log_record_count"],
                "review_record_count": profile["review_record_count"],
                "human_failure_record_count": profile["human_failure_record_count"],
                "source_negative_files": profile["source_negative_files"],
                "source_failure_log_files": profile["source_failure_log_files"],
                "source_review_rows_files": profile["source_review_rows_files"],
                "source_place_review_feedback_files": profile[
                    "source_place_review_feedback_files"
                ],
                "source_gold_examples_file": profile["source_gold_examples_file"],
                "activate_with": f"MAP_LEARNING_PROFILE_PATH={output_path}",
                "latest_profile_path": str(args.out_dir / "map_learning_profile_latest.json"),
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0 if profile["validation"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

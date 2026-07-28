from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import daily_map_game
from tools import training_data_store

DEFAULT_TRAINING_DIR = PROJECT_DIR / "data" / "training"
DEFAULT_PROFILE_PATH = DEFAULT_TRAINING_DIR / "map_selector_profile_latest.json"
DEFAULT_DB_PATH = PROJECT_DIR / "data" / "fultons.db"
DEFAULT_OUTPUT_PATH = DEFAULT_TRAINING_DIR / training_data_store.MAP_PLACE_REVIEW_FEEDBACK_ALL


def hard_reviews_by_place(profile: dict[str, Any]) -> dict[str, dict[str, str]]:
    section = profile.get("hard_clue_review")
    if not isinstance(section, dict):
        return {}
    results: dict[str, dict[str, str]] = {}
    for verdict, key in (
        ("pass", "pass_examples"),
        ("pass", "qualified_pass_examples"),
        ("fail", "fail_examples"),
    ):
        examples = section.get(key)
        if not isinstance(examples, list):
            continue
        for example in examples:
            if not isinstance(example, dict):
                continue
            place = str(example.get("place") or "").strip()
            if not place:
                continue
            results[place] = {
                "pass_fail": verdict,
                "clue": str(example.get("clue") or "").strip(),
                "reason": str(example.get("reason") or "").strip(),
                "better_direction": str(example.get("better_direction") or "").strip(),
            }
    return results


def notes_by_place(profile: dict[str, Any]) -> dict[str, list[str]]:
    results: dict[str, list[str]] = {}
    guidance = profile.get("note_guidance")
    if not isinstance(guidance, list):
        return results
    for item in guidance:
        examples = item.get("examples") if isinstance(item, dict) else None
        if not isinstance(examples, list):
            continue
        for example in examples:
            if not isinstance(example, dict):
                continue
            place = str(example.get("place") or "").strip()
            note = str(example.get("note") or "").strip()
            if place and note and note not in results.setdefault(place, []):
                results[place].append(note)
    return results


def recover_rows(
    profile: dict[str, Any],
    conn: sqlite3.Connection,
) -> tuple[list[dict[str, Any]], int]:
    place_scores = profile.get("place_scores")
    if not isinstance(place_scores, dict):
        raise ValueError("Selector profile has no place_scores object.")
    hard_reviews = hard_reviews_by_place(profile)
    review_notes = notes_by_place(profile)
    rows: list[dict[str, Any]] = []
    matched = 0
    for place, raw_score in place_scores.items():
        name = str(place).strip()
        if not name:
            continue
        try:
            score = int(raw_score)
        except (TypeError, ValueError):
            continue
        db_row = conn.execute(
            "SELECT * FROM map_place_pool WHERE canonical_name = ?",
            (name,),
        ).fetchone()
        recovered: dict[str, Any] = {
            "place": name,
            "canonical_name": name,
            "your_score": score,
            "notes": " ".join(review_notes.get(name, [])),
            "hard_review": hard_reviews.get(name, {}),
            "source": "selector_profile_recovery",
        }
        if db_row is not None:
            matched += 1
            payload = daily_map_game.public_place_payload(db_row)
            selection = daily_map_game.map_place_selection_profile(db_row, {})
            facts = payload.get("verified_facts")
            recovered.update(
                {
                    "type": str(db_row["place_type"] or ""),
                    "place_type": str(db_row["place_type"] or ""),
                    "difficulty": str(db_row["difficulty"] or ""),
                    "country_code": str(db_row["country_code"] or ""),
                    "country_name": str(db_row["country_name"] or ""),
                    "admin1": str(db_row["admin1"] or ""),
                    "categories": ";".join(selection.get("categories") or []),
                    "machine_score": int(selection.get("score") or 0),
                    "base_score": int(selection.get("score") or 0),
                    "workoutability_score": int(selection.get("workoutabilityScore") or 0),
                    "facts": facts if isinstance(facts, list) else [],
                    "clues": {
                        "hard": str(db_row["clue_text"] or ""),
                        "medium": str(db_row["medium_clue_text"] or ""),
                        "easy": str(db_row["easy_clue_text"] or ""),
                        "reveal": str(db_row["reveal_text"] or ""),
                    },
                    "map_guessability": str(db_row["nearby_context"] or ""),
                }
            )
        rows.append(recovered)
    return rows, matched


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recover deduplicated map review rows from the retained selector profile.",
    )
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows, matched = recover_rows(profile, conn)
    finally:
        conn.close()
    added = training_data_store.merge_map_place_review_feedback_rows(
        args.out,
        rows,
        source_file=str(args.profile),
        reconstructed=True,
    )
    print(
        json.dumps(
            {
                "output_path": str(args.out),
                "profile_place_count": len(rows),
                "database_matched_count": matched,
                "added_count": added,
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

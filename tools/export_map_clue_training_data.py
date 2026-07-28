from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import daily_map_game

DEFAULT_DB_PATH = PROJECT_DIR / "data" / "fultons.db"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "data" / "training"
SYSTEM_MESSAGE = "Return one valid JSON object only. Do not use markdown."


@dataclass(frozen=True)
class ExportResult:
    train_path: Path
    eval_path: Path
    negative_path: Path
    manifest_path: Path
    train_count: int
    eval_count: int
    negative_count: int
    approved_count: int
    positive_count: int
    quality_excluded_count: int


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")


def approved_record(row: sqlite3.Row) -> dict[str, Any]:
    place = daily_map_game.public_place_payload(row)
    clue_ladder = {
        "hard": row["clue_text"],
        "medium": row["medium_clue_text"],
        "easy": row["easy_clue_text"],
        "reveal": row["reveal_text"],
    }
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_MESSAGE},
            {
                "role": "user",
                "content": daily_map_game.map_clue_generator_prompt(place, [], []),
            },
            {"role": "assistant", "content": json.dumps(clue_ladder, ensure_ascii=True)},
        ],
        "metadata": {
            "place": row["canonical_name"],
            "place_type": row["place_type"],
            "difficulty": row["difficulty"],
            "review_status": row["review_status"],
        },
    }


def eval_record(row: sqlite3.Row) -> dict[str, Any]:
    place = daily_map_game.public_place_payload(row)
    return {
        "input": {
            "system": SYSTEM_MESSAGE,
            "prompt": daily_map_game.map_clue_generator_prompt(place, [], []),
        },
        "expected": {
            "hard": row["clue_text"],
            "medium": row["medium_clue_text"],
            "easy": row["easy_clue_text"],
            "reveal": row["reveal_text"],
        },
        "metadata": {
            "place": row["canonical_name"],
            "place_type": row["place_type"],
            "difficulty": row["difficulty"],
        },
    }


def negative_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "failure_reason": row["review_notes"] or "Rejected during map clue review.",
        "feedback_to_generator": row["review_notes"] or "Improve clue distinctiveness and verification.",
        "metadata": {
            "place": row["canonical_name"],
            "place_type": row["place_type"],
            "difficulty": row["difficulty"],
            "review_status": row["review_status"],
            "active": bool(row["active"]),
        },
    }


def row_clue_ladder(row: sqlite3.Row) -> dict[str, str]:
    return {
        "hard": str(row["clue_text"] or ""),
        "medium": str(row["medium_clue_text"] or ""),
        "easy": str(row["easy_clue_text"] or ""),
        "reveal": str(row["reveal_text"] or ""),
    }


def quality_gate_negative_record(row: sqlite3.Row, critic: dict[str, Any]) -> dict[str, Any]:
    reasons = [str(reason) for reason in critic.get("failure_reasons") or [] if str(reason).strip()]
    feedback = [
        str(item)
        for item in critic.get("feedback_to_generator") or []
        if str(item).strip()
    ]
    return {
        "failure_reason": "; ".join(reasons) or "Rejected by map clue quality gate.",
        "feedback_to_generator": feedback or ["Improve clue concision, specificity, and natural wording."],
        "metadata": {
            "reason": "map_clue_quality_gate",
            "place": row["canonical_name"],
            "place_type": row["place_type"],
            "difficulty": row["difficulty"],
            "review_status": row["review_status"],
        },
    }


def seed_negative_records() -> list[dict[str, Any]]:
    return [
        {
            "failure_reason": "The hard, medium, and easy clues repeat the same river-and-capital information.",
            "feedback_to_generator": "Avoid a repetitive ladder: make each clue level introduce a different verified hook rather than restating the same clue more clearly.",
            "metadata": {
                "reason": "seeded_map_clue_anti_pattern",
                "place_type": "*",
                "difficulty": "*",
            },
        },
        {
            "failure_reason": "The clue uses coordinates, compass degrees, or an ISO country code as the targeting mechanism.",
            "feedback_to_generator": "Do not use latitude, longitude, compass degrees, ISO codes, coordinates, or database-like identifiers as clues.",
            "metadata": {
                "reason": "seeded_map_clue_anti_pattern",
                "place_type": "*",
                "difficulty": "*",
            },
        },
        {
            "failure_reason": "The clue reveals the answer name or an accepted alias before the final reveal.",
            "feedback_to_generator": "Keep the canonical name and aliases out of hard, medium, and easy clues; only the final reveal may name the answer.",
            "metadata": {
                "reason": "seeded_map_clue_anti_pattern",
                "place_type": "*",
                "difficulty": "*",
            },
        },
        {
            "failure_reason": "The clue is generic and could fit many towns, cities, or landmarks.",
            "feedback_to_generator": "Avoid generic clues that could fit many places; use specific source-backed hooks such as a visible landmark, coastline, river bend, old town, bridge, stadium, monument, or historic role.",
            "metadata": {
                "reason": "seeded_map_clue_anti_pattern",
                "place_type": "*",
                "difficulty": "*",
            },
        },
        {
            "failure_reason": "The reveal reads like coordinate or time-zone metadata rather than a natural answer explanation.",
            "feedback_to_generator": "Make the reveal a natural explanation; do not mention coordinates, time zones, or database metadata.",
            "metadata": {
                "reason": "seeded_map_clue_anti_pattern",
                "place_type": "*",
                "difficulty": "*",
            },
        },
    ]


def choose_eval_indexes(count: int, eval_fraction: float) -> set[int]:
    if count <= 1 or eval_fraction <= 0:
        return set()
    eval_count = max(1, min(count - 1, round(count * eval_fraction)))
    interval = count / eval_count
    return {min(count - 1, int(round((index + 0.5) * interval - 0.5))) for index in range(eval_count)}


def export_map_clue_training_data(
    db_path: Path = DEFAULT_DB_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    eval_fraction: float = 0.12,
    include_seed_negatives: bool = True,
) -> ExportResult:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        daily_map_game.initialize_database(conn)
        approved = conn.execute(
            """
            SELECT *
            FROM map_place_pool
            WHERE review_status IN ('approved', 'machine_validated')
              AND active = 1
              AND clue_text <> ''
              AND medium_clue_text <> ''
              AND easy_clue_text <> ''
              AND reveal_text <> ''
            ORDER BY canonical_name
            """
        ).fetchall()
        rejected = conn.execute(
            """
            SELECT *
            FROM map_place_pool
            WHERE review_status = 'rejected'
            ORDER BY canonical_name
            """
        ).fetchall()
    finally:
        conn.close()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir.mkdir(parents=True, exist_ok=True)
    train_path = output_dir / f"map_clue_sft_train_{stamp}.jsonl"
    eval_path = output_dir / f"map_clue_eval_{stamp}.jsonl"
    negative_path = output_dir / f"map_clue_negative_{stamp}.jsonl"
    manifest_path = output_dir / f"map_clue_manifest_{stamp}.json"

    positive_rows: list[sqlite3.Row] = []
    quality_negative_rows: list[dict[str, Any]] = []
    for row in approved:
        critic = daily_map_game.local_map_clue_critique(
            daily_map_game.public_place_payload(row),
            row_clue_ladder(row),
        )
        if daily_map_game.map_clue_critic_passed(critic):
            positive_rows.append(row)
        else:
            quality_negative_rows.append(quality_gate_negative_record(row, critic))

    eval_indexes = choose_eval_indexes(len(positive_rows), eval_fraction)
    train_rows = [
        approved_record(row)
        for index, row in enumerate(positive_rows)
        if index not in eval_indexes
    ]
    eval_rows = [
        eval_record(row)
        for index, row in enumerate(positive_rows)
        if index in eval_indexes
    ]
    negative_rows = [negative_record(row) for row in rejected]
    negative_rows.extend(quality_negative_rows)
    if include_seed_negatives:
        negative_rows.extend(seed_negative_records())
    write_jsonl(train_path, train_rows)
    write_jsonl(eval_path, eval_rows)
    write_jsonl(negative_path, negative_rows)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "train_path": str(train_path),
        "eval_path": str(eval_path),
        "negative_path": str(negative_path),
        "approved_count": len(approved),
        "positive_count": len(positive_rows),
        "quality_excluded_count": len(quality_negative_rows),
        "train_count": len(train_rows),
        "eval_count": len(eval_rows),
        "negative_count": len(negative_rows),
        "eval_fraction": eval_fraction,
        "include_seed_negatives": include_seed_negatives,
        "format": {
            "train": "OpenAI chat fine-tuning JSONL with messages",
            "eval": "Held-out map clue prompt, expected output, and metadata JSONL",
            "negative": "Rejected rows and seeded anti-pattern feedback for learning-profile construction",
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    return ExportResult(
        train_path=train_path,
        eval_path=eval_path,
        negative_path=negative_path,
        manifest_path=manifest_path,
        train_count=len(train_rows),
        eval_count=len(eval_rows),
        negative_count=len(negative_rows),
        approved_count=len(approved),
        positive_count=len(positive_rows),
        quality_excluded_count=len(quality_negative_rows),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export reviewed map clue examples to JSONL.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--eval-fraction", type=float, default=0.12)
    parser.add_argument("--no-seed-negatives", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = export_map_clue_training_data(
        args.db,
        args.out_dir,
        eval_fraction=args.eval_fraction,
        include_seed_negatives=not args.no_seed_negatives,
    )
    print(
        json.dumps(
            {
                "train_path": str(result.train_path),
                "eval_path": str(result.eval_path),
                "negative_path": str(result.negative_path),
                "manifest_path": str(result.manifest_path),
                "approved_count": result.approved_count,
                "positive_count": result.positive_count,
                "quality_excluded_count": result.quality_excluded_count,
                "train_count": result.train_count,
                "eval_count": result.eval_count,
                "negative_count": result.negative_count,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

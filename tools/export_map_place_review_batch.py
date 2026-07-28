from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import daily_map_game
from tools import map_selector_model

DEFAULT_DB_PATH = PROJECT_DIR / "data" / "fultons.db"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "data" / "training"
DEFAULT_PUBLIC_PATH = PROJECT_DIR / "public" / "map-place-review.html"


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def mask_names(text: str, names: list[str], replacement: str = "this place") -> str:
    result = str(text or "")
    candidates = sorted(
        {name.strip() for name in names if len(name.strip()) >= 4},
        key=len,
        reverse=True,
    )
    for name in candidates:
        result = re.sub(re.escape(name), replacement, result, flags=re.IGNORECASE)
    return result


def place_aliases(row: sqlite3.Row) -> list[str]:
    return [
        row["canonical_name"],
        *daily_map_game.split_list_text(row["acceptable_aliases"]),
    ]


def row_text(row: dict[str, Any], key: str) -> str:
    return html.unescape(str(row.get(key) or "").strip())


def review_clue_uses(row: dict[str, Any]) -> list[dict[str, Any]]:
    fact_1 = row_text(row, "fact_1")
    fact_2 = row_text(row, "fact_2")
    fact_3 = row_text(row, "fact_3")
    hard = row_text(row, "hard_clue") or fact_1
    medium = row_text(row, "medium_clue") or fact_2
    easy = row_text(row, "easy_clue") or fact_3
    reveal = row_text(row, "reveal_text") or row_text(row, "canonical_name")
    return [
        {
            "level": "Hard",
            "maxPoints": daily_map_game.MAP_CLUE_SCORES[0],
            "role": "Recognition hook: a verified place-owned incident, story, record, achievement, association, tradition, or phenomenon.",
            "fact": fact_1,
            "usedAs": hard,
        },
        {
            "level": "Medium",
            "maxPoints": daily_map_game.MAP_CLUE_SCORES[1],
            "role": "Geographic narrowing: reduces the world to a useful country, region, culture, language, city, or equivalent scope.",
            "fact": fact_2,
            "usedAs": medium,
        },
        {
            "level": "Easy",
            "maxPoints": daily_map_game.MAP_CLUE_SCORES[2],
            "role": "Local map route: narrows within medium's area to a borough, district, quarter, city sector, or visible local feature.",
            "fact": fact_3,
            "usedAs": easy,
        },
        {
            "level": "Name",
            "maxPoints": daily_map_game.MAP_CLUE_SCORES[3],
            "role": "Final reveal: gives the place name only, leaving the player to find and pin it.",
            "fact": "",
            "usedAs": reveal,
        },
    ]


def review_candidates(db_path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    daily_map_game.initialize_database(conn)
    selector_profile = daily_map_game.load_map_selector_profile()
    selector_model = map_selector_model.load_model()
    rows = conn.execute(
        """
        SELECT *
        FROM map_place_pool
        WHERE active = 1
          AND review_status = 'approved'
          AND clue_text <> ''
          AND reveal_text <> ''
        """
    ).fetchall()
    candidates = []
    for row in rows:
        if not daily_map_game.row_passes_map_clue_quality(row):
            continue
        profile = daily_map_game.map_place_selection_profile(row, selector_profile)
        aliases = place_aliases(row)
        facts = [
            mask_names(str(item["text"]), aliases, replacement="this place")
            for item in profile["persuadingFacts"]
        ]
        clue_ladder = daily_map_game.clue_ladder_for_row(row)
        clue_text_by_id = {
            str(clue["id"]): mask_names(str(clue["text"]), aliases, replacement="this place")
            for clue in clue_ladder
            if str(clue.get("id") or "") != "name"
        }
        review_row = {
            "interest_score": int(profile["score"]),
            "base_score": int(profile["baseScore"]),
            "feedback_adjustment": int(profile["feedbackAdjustment"]),
            "persuading_fact_count": int(profile["persuadingFactCount"]),
            "workoutability_score": int(profile["workoutabilityScore"]),
            "canonical_name": row["canonical_name"],
            "place_type": row["place_type"],
            "difficulty": row["difficulty"],
            "country_name": row["country_name"] or daily_map_game.country_name(row["country_code"]),
            "admin1": row["admin1"] or "",
            "categories": "; ".join(profile["categories"]),
            "fact_1": facts[0] if len(facts) > 0 else "",
            "fact_2": facts[1] if len(facts) > 1 else "",
            "fact_3": facts[2] if len(facts) > 2 else "",
            "hard_clue": clue_text_by_id.get("hard", ""),
            "medium_clue": clue_text_by_id.get("medium", ""),
            "easy_clue": clue_text_by_id.get("easy", ""),
            "reveal_text": row["canonical_name"],
            "your_score_0_10": "",
            "your_notes": "",
        }
        review_row.update(map_selector_model.predict_score(selector_model, review_row))
        candidates.append(review_row)
    candidates.sort(
        key=lambda item: (
            float(item.get("ml_rank_score") or item["interest_score"]),
            float(item.get("ml_score") or 0),
            item["interest_score"],
            item["persuading_fact_count"],
            item["canonical_name"],
        ),
        reverse=True,
    )
    return candidates


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "interest_score",
        "ml_score",
        "ml_confidence",
        "ml_rank_score",
        "base_score",
        "feedback_adjustment",
        "your_score_0_10",
        "your_notes",
        "canonical_name",
        "place_type",
        "difficulty",
        "country_name",
        "admin1",
        "persuading_fact_count",
        "categories",
        "fact_1",
        "fact_2",
        "fact_3",
        "hard_clue",
        "medium_clue",
        "easy_clue",
        "reveal_text",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_review_page(path: Path, rows: list[dict[str, Any]]) -> None:
    places = [
        {
            "place": row["canonical_name"],
            "type": row["place_type"],
            "difficulty": row["difficulty"],
            "country": row["country_name"],
            "admin1": row["admin1"],
            "score": row["interest_score"],
            "mlScore": row.get("ml_score", ""),
            "mlConfidence": row.get("ml_confidence", ""),
            "mlRankScore": row.get("ml_rank_score", ""),
            "baseScore": row["base_score"],
            "feedbackAdjustment": row["feedback_adjustment"],
            "categories": row["categories"],
            "source": row.get("source", "existing_bank"),
            "candidateId": row.get("candidate_id", ""),
            "whyFun": row.get("why_fun", ""),
            "mapGuessability": row.get("map_guessability", ""),
            "clueUses": review_clue_uses(row),
            "clues": {
                "hard": row_text(row, "hard_clue") or row_text(row, "fact_1"),
                "medium": row_text(row, "medium_clue") or row_text(row, "fact_2"),
                "easy": row_text(row, "easy_clue") or row_text(row, "fact_3"),
                "reveal": row_text(row, "reveal_text") or row_text(row, "canonical_name"),
            },
            "facts": [
                fact
                for fact in [row["fact_1"], row["fact_2"], row["fact_3"]]
                if str(fact).strip()
            ],
        }
        for row in rows
    ]
    template_path = PROJECT_DIR / "tools" / "templates" / "map-place-review.html"
    template = template_path.read_text(encoding="utf-8")
    places_json = json.dumps(places, ensure_ascii=False)
    batch_id = hashlib.sha1(
        (places_json + "|complete_ladder_gold_profile_v1").encode("utf-8")
    ).hexdigest()[:12]
    start = template.index("const places = ")
    end = template.index(";\nconst storageKey", start)
    updated = template[:start] + f"const places = {places_json}" + template[end:]
    storage_start = updated.index("const storageKey = ")
    storage_end = updated.index(";\nconst reviewPhase", storage_start)
    updated = (
        updated[:storage_start]
        + f"const storageKey = 'fultons-map-place-review-{batch_id}'"
        + updated[storage_end:]
    )
    path.write_text(updated, encoding="utf-8")


def diversified_batch(candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    remaining = list(candidates)
    selected: list[dict[str, Any]] = []
    type_counts: dict[str, int] = {}
    soft_cap = 4
    while remaining and len(selected) < limit:
        picked_index = None
        for index, candidate in enumerate(remaining):
            place_type = str(candidate["place_type"])
            if type_counts.get(place_type, 0) < soft_cap:
                picked_index = index
                break
        if picked_index is None:
            soft_cap += 2
            continue
        candidate = remaining.pop(picked_index)
        selected.append(candidate)
        place_type = str(candidate["place_type"])
        type_counts[place_type] = type_counts.get(place_type, 0) + 1
    return selected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a masked map place review batch.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--public-page", type=Path, default=DEFAULT_PUBLIC_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    batch = diversified_batch(review_candidates(args.db), max(1, args.limit))
    stamp = timestamp()
    csv_path = args.out_dir / f"map_place_selection_batch_{len(batch)}_{stamp}.csv"
    write_csv(csv_path, batch)
    write_review_page(args.public_page, batch)
    print(
        json.dumps(
            {
                "batch_count": len(batch),
                "csv_path": str(csv_path),
                "public_page": str(args.public_page),
                "top_10": [
                    {
                        "score": item["interest_score"],
                        "mlScore": item.get("ml_score", ""),
                        "mlRankScore": item.get("ml_rank_score", ""),
                        "baseScore": item["base_score"],
                        "feedbackAdjustment": item["feedback_adjustment"],
                        "place": item["canonical_name"],
                        "type": item["place_type"],
                    }
                    for item in batch[:10]
                ],
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

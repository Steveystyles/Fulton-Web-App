from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import daily_map_game
from tools import export_map_place_review_batch as review_export
from tools import generate_ai_daily_map_round as daily_generator
from tools import rewrite_map_clues_with_ai as rewriter
DEFAULT_DB_PATH = PROJECT_DIR / "data" / "fultons.db"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "data" / "training"
DEFAULT_PUBLIC_PATH = PROJECT_DIR / "public" / "map-place-review.html"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def review_row(
    row: sqlite3.Row,
    *,
    candidate: dict[str, Any],
    selection_reason: str,
    generation: dict[str, Any],
) -> dict[str, Any]:
    ladder = generation["clue_ladder"]
    return {
        "interest_score": int(candidate.get("selector_score") or 0),
        "ml_score": candidate.get("learned_score", ""),
        "ml_confidence": candidate.get("learned_confidence", ""),
        "ml_rank_score": "",
        "base_score": int(candidate.get("selector_score") or 0),
        "feedback_adjustment": 0,
        "canonical_name": str(row["canonical_name"]),
        "place_type": str(row["place_type"]),
        "difficulty": str(row["difficulty"]),
        "country_name": str(row["country_name"] or row["country_code"]),
        "admin1": str(row["admin1"] or ""),
        "categories": "; ".join(str(value) for value in candidate.get("categories") or []),
        "fact_1": str(
            candidate.get("enriched_hard_hook")
            or candidate.get("verified_hard_hook")
            or ""
        ),
        "fact_2": "",
        "fact_3": "",
        "hard_clue": str(ladder["hard"]),
        "medium_clue": str(ladder["medium"]),
        "easy_clue": str(ladder["easy"]),
        "reveal_text": str(ladder["reveal"]),
        "source": "ai_hook_first_review_batch",
        "candidate_id": str(row["id"]),
        "why_fun": selection_reason,
        "map_guessability": str(candidate.get("map_guessability") or ""),
        "selected_hard_hook": str(candidate.get("verified_hard_hook") or ""),
        "enriched_hard_hook": str(candidate.get("enriched_hard_hook") or ""),
        "event_source_urls": list(candidate.get("event_source_urls") or []),
        "generation_attempts": len(generation.get("attempts") or []),
        "critic_mode": str(generation.get("critic_mode") or ""),
    }


def review_batch_exclusions(
    conn: sqlite3.Connection,
    *,
    puzzle_date: str,
) -> tuple[set[int], set[str]]:
    valid_date = daily_map_game.valid_game_date(puzzle_date)
    cutoff = (
        datetime.strptime(valid_date, "%Y-%m-%d")
        - timedelta(days=daily_map_game.RECENT_USE_DAYS)
    ).date().isoformat()
    used_ids = {
        int(row["place_id"])
        for row in conn.execute(
            """
            SELECT DISTINCT daily_map_levels.place_id
            FROM daily_map_levels
            INNER JOIN daily_map_puzzles
                ON daily_map_puzzles.id = daily_map_levels.puzzle_id
            WHERE daily_map_puzzles.puzzle_date >= ?
              AND daily_map_puzzles.puzzle_date <= ?
            """,
            (cutoff, valid_date),
        ).fetchall()
    }
    # Review results are labels for learning, not a permanent allowlist or blacklist.
    return used_ids, set()


def generate_batch(
    conn: sqlite3.Connection,
    *,
    provider: rewriter.ConfiguredMapClueProvider,
    puzzle_date: str,
    count: int,
    shortlist_limit: int,
    max_clue_attempts: int,
    eligible_names: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    daily_map_game.initialize_database(conn)
    available = daily_generator.hard_hook_shortlist(
        conn,
        puzzle_date=puzzle_date,
        limit=max(count * 3, shortlist_limit),
        eligible_names=eligible_names,
    )
    used_ids, gold_names = review_batch_exclusions(conn, puzzle_date=puzzle_date)
    available = [
        candidate
        for candidate in available
        if int(candidate["place_id"]) not in used_ids
        and str(candidate["place"]).strip().casefold() not in gold_names
    ]
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    while available and len(rows) < count:
        candidate, selection_reason = daily_generator.choose_learned_hard_hook(available)
        place_id = int(candidate["place_id"])
        available = [item for item in available if int(item["place_id"]) != place_id]
        place = conn.execute(
            "SELECT * FROM map_place_pool WHERE id = ?",
            (place_id,),
        ).fetchone()
        if place is None:
            failures.append({"place_id": place_id, "reason": "Place disappeared before generation."})
            continue
        place_payload = daily_map_game.public_place_payload(place)
        try:
            event_brief = daily_generator.research_event_brief(
                provider,
                candidate,
                place=place_payload,
            )
        except Exception as error:
            failures.append(
                {
                    "place_id": place_id,
                    "place": str(place["canonical_name"]),
                    "verified_hard_hook": str(candidate["verified_hard_hook"]),
                    "reason": f"Grounded recognition-hook research failed: {error}",
                }
            )
            continue
        candidate = {
            **candidate,
            "enriched_hard_hook": str(event_brief["enriched_hard_hook"]),
            "event_source_urls": list(event_brief["used_source_urls"]),
            "event_supporting_details": list(event_brief["supporting_details"]),
        }
        print(
            json.dumps(
                {
                    "stage": "generating",
                    "accepted": len(rows),
                    "target": count,
                    "place_id": place_id,
                    "place": str(place["canonical_name"]),
                    "verified_hard_hook": str(candidate["verified_hard_hook"]),
                    "enriched_hard_hook": str(candidate["enriched_hard_hook"]),
                },
                ensure_ascii=True,
            ),
            flush=True,
        )
        try:
            generation = daily_map_game.generate_reviewed_clue_ladder(
                conn,
                place_id=place_id,
                provider=provider,
                config=daily_map_game.MapClueConfig(
                    learning_profile_path=daily_map_game.DEFAULT_MAP_LEARNING_PROFILE_PATH,
                    clue_quality_model_path=daily_map_game.DEFAULT_MAP_CLUE_QUALITY_MODEL_PATH,
                    max_attempts_per_place=max(1, max_clue_attempts),
                    require_ai_critic=True,
                ),
                save=False,
                required_hard_hook=str(candidate["enriched_hard_hook"]),
            )
        except Exception as error:
            failures.append(
                {
                    "place_id": place_id,
                    "place": str(place["canonical_name"]),
                    "verified_hard_hook": str(candidate["verified_hard_hook"]),
                    "enriched_hard_hook": str(candidate["enriched_hard_hook"]),
                    "reason": f"Clue generation provider failed: {error}",
                }
            )
            continue
        if generation.get("status") != "accepted":
            failures.append(
                {
                    "place_id": place_id,
                    "place": str(place["canonical_name"]),
                    "verified_hard_hook": str(candidate["verified_hard_hook"]),
                    "enriched_hard_hook": str(candidate["enriched_hard_hook"]),
                    "reason": "No clue ladder passed both critics.",
                    "attempts": generation.get("attempts") or [],
                }
            )
            continue
        rows.append(
            review_row(
                place,
                candidate=candidate,
                selection_reason=selection_reason,
                generation=generation,
            )
        )
    return rows, failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an AI-selected map batch for human place and clue review.",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--date", default=datetime.now().date().isoformat())
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--shortlist-limit", type=int, default=40)
    parser.add_argument("--max-clue-attempts", type=int, default=5)
    parser.add_argument(
        "--discover-count",
        type=int,
        default=-1,
        help="Fresh grounded candidates to generate first. The default automatically uses twice the requested review count.",
    )
    parser.add_argument("--env-file", type=Path, default=rewriter.DEFAULT_ENV_FILE)
    parser.add_argument("--generator-model", default="")
    parser.add_argument("--critic-model", default="")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--public-page", type=Path, default=DEFAULT_PUBLIC_PATH)
    parser.add_argument("--timeout-sec", type=int, default=None)
    parser.add_argument("--request-delay-sec", type=float, default=None)
    parser.add_argument("--transient-retries", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rewriter.load_env_file(args.env_file)
    rewriter.apply_runtime_env_overrides(args)
    provider = rewriter.ConfiguredMapClueProvider.from_env(
        generator_model=args.generator_model,
        critic_model=args.critic_model,
    )
    discovery_count = (
        max(4, args.count * 2)
        if args.discover_count < 0
        else max(0, args.discover_count)
    )
    discovery: dict[str, Any] | None = None
    eligible_names: set[str] | None = None
    if discovery_count:
        discovery = daily_generator.discover_uncurated_candidates(
            db_path=args.db,
            provider=provider,
            puzzle_date=args.date,
            count=discovery_count,
            max_attempts=4,
        )
        eligible_names = set(discovery["candidate_names"])
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows, failures = generate_batch(
            conn,
            provider=provider,
            puzzle_date=args.date,
            count=max(1, args.count),
            shortlist_limit=max(args.count, args.shortlist_limit),
            max_clue_attempts=max(1, args.max_clue_attempts),
            eligible_names=eligible_names,
        )
    finally:
        conn.close()

    if not rows:
        raise SystemExit(
            "No critic-approved review rounds were generated: "
            + json.dumps(failures, ensure_ascii=True)
        )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_stamp()
    report_path = args.out_dir / f"map_ai_review_batch_{len(rows)}_{stamp}.json"
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "requested_count": max(1, args.count),
        "generated_count": len(rows),
        "learning_profile_hash": daily_map_game.map_learning_profile_hash(),
        "discovery": discovery,
        "model_summary": provider.model_summary(),
        "rows": rows,
        "failures": failures,
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    review_export.write_review_page(args.public_page, rows)
    print(
        json.dumps(
            {
                "generated_count": len(rows),
                "failure_count": len(failures),
                "report_path": str(report_path),
                "public_page": str(args.public_page),
            },
            indent=2,
        )
    )
    return 0 if len(rows) >= max(1, args.count) else 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import daily_map_game


SCHEMA_VERSION = 1
PLACE_REQUIRED_FIELDS = {
    "slug",
    "canonical_name",
    "country_code",
    "lat",
    "lng",
    "clue_text",
    "medium_clue_text",
    "easy_clue_text",
    "reveal_text",
    "map_search_anchors_json",
}
LEVEL_FIELDS = ("level_slug", "max_points", "lambda_km")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")]


def validate_package(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError(f"Launch package schemaVersion must be {SCHEMA_VERSION}.")
    puzzle = payload.get("puzzle")
    place = payload.get("place")
    level = payload.get("level")
    if not isinstance(puzzle, dict) or not isinstance(place, dict) or not isinstance(level, dict):
        raise ValueError("Launch package must contain puzzle, place, and level objects.")
    daily_map_game.valid_game_date(str(puzzle.get("date") or ""))
    missing = sorted(field for field in PLACE_REQUIRED_FIELDS if field not in place)
    if missing:
        raise ValueError("Launch place is missing: " + ", ".join(missing))
    if any(field not in level for field in LEVEL_FIELDS):
        raise ValueError("Launch level is missing required scoring fields.")
    anchors = daily_map_game.parse_json_list(place.get("map_search_anchors_json"))
    medium = [anchor for anchor in anchors if int(anchor.get("min_hint_count") or 0) == 1]
    easy = [anchor for anchor in anchors if int(anchor.get("min_hint_count") or 0) == 2]
    if not medium or not easy:
        raise ValueError("Launch round must contain staged medium and easy map anchors.")
    if not any(anchor.get("boundary_kind") == "guidance" for anchor in medium):
        raise ValueError("Launch medium guidance must use a soft search area.")
    if str(level.get("level_slug") or "") not in {"easy", "medium", "hard"}:
        raise ValueError("Launch level_slug is invalid.")
    return payload


def export_round(conn: sqlite3.Connection, puzzle_date: str) -> dict[str, Any]:
    normalized_date = daily_map_game.valid_game_date(puzzle_date)
    row = conn.execute(
        """
        SELECT daily_map_puzzles.*, daily_map_levels.id AS level_id,
               daily_map_levels.level_slug, daily_map_levels.max_points,
               daily_map_levels.lambda_km, daily_map_levels.place_id
        FROM daily_map_puzzles
        JOIN daily_map_levels ON daily_map_levels.puzzle_id = daily_map_puzzles.id
        WHERE daily_map_puzzles.puzzle_date = ?
        ORDER BY daily_map_levels.id
        LIMIT 1
        """,
        (normalized_date,),
    ).fetchone()
    if row is None or row["status"] != "published":
        raise ValueError(f"No published map round exists for {normalized_date}.")
    place = conn.execute("SELECT * FROM map_place_pool WHERE id = ?", (row["place_id"],)).fetchone()
    if place is None:
        raise ValueError("The launch round place is missing.")
    place_payload = {key: place[key] for key in place.keys() if key != "id"}
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "exportedAt": utc_now(),
        "puzzle": {"date": normalized_date, "status": "published"},
        "place": place_payload,
        "level": {field: row[field] for field in LEVEL_FIELDS},
    }
    return validate_package(payload)


def import_round(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    target_date: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    validated = validate_package(payload)
    package_date = str(validated["puzzle"]["date"])
    puzzle_date = daily_map_game.valid_game_date(target_date or package_date)
    place_payload = dict(validated["place"])
    level_payload = dict(validated["level"])

    existing = conn.execute(
        "SELECT id, status FROM daily_map_puzzles WHERE puzzle_date = ?",
        (puzzle_date,),
    ).fetchone()
    if existing is not None:
        guess_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM daily_map_guesses
            JOIN daily_map_levels ON daily_map_levels.id = daily_map_guesses.level_id
            WHERE daily_map_levels.puzzle_id = ?
            """,
            (existing["id"],),
        ).fetchone()[0]
        if guess_count:
            raise ValueError(f"Cannot replace {puzzle_date}; it already has submitted guesses.")

    place_columns = [
        column
        for column in table_columns(conn, "map_place_pool")
        if column != "id" and column in place_payload
    ]
    unknown_required = PLACE_REQUIRED_FIELDS.difference(place_columns)
    if unknown_required:
        raise ValueError("Production map schema is missing: " + ", ".join(sorted(unknown_required)))

    result = {
        "date": puzzle_date,
        "place": str(place_payload["canonical_name"]),
        "status": "validated" if dry_run else "published",
    }
    if dry_run:
        return result

    conn.execute("SAVEPOINT import_map_launch_round")
    try:
        placeholders = ", ".join("?" for _ in place_columns)
        updates = ", ".join(
            f"{column} = excluded.{column}" for column in place_columns if column != "slug"
        )
        conn.execute(
            f"""
            INSERT INTO map_place_pool ({', '.join(place_columns)})
            VALUES ({placeholders})
            ON CONFLICT(slug) DO UPDATE SET {updates}
            """,
            tuple(place_payload[column] for column in place_columns),
        )
        place_id = conn.execute(
            "SELECT id FROM map_place_pool WHERE slug = ?",
            (place_payload["slug"],),
        ).fetchone()[0]
        if existing is None:
            cursor = conn.execute(
                """
                INSERT INTO daily_map_puzzles (
                    puzzle_date, status, generated_at, published_at, failure_reason
                ) VALUES (?, 'published', ?, ?, NULL)
                """,
                (puzzle_date, utc_now(), utc_now()),
            )
            puzzle_id = cursor.lastrowid
        else:
            puzzle_id = existing["id"]
            conn.execute("DELETE FROM daily_map_levels WHERE puzzle_id = ?", (puzzle_id,))
            conn.execute(
                """
                UPDATE daily_map_puzzles
                SET status = 'published', generated_at = ?, published_at = ?, failure_reason = NULL
                WHERE id = ?
                """,
                (utc_now(), utc_now(), puzzle_id),
            )
        conn.execute(
            """
            INSERT INTO daily_map_levels (
                puzzle_id, level_slug, place_id, max_points, lambda_km, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                puzzle_id,
                level_payload["level_slug"],
                place_id,
                int(level_payload["max_points"]),
                float(level_payload["lambda_km"]),
                utc_now(),
            ),
        )
        conn.execute("RELEASE SAVEPOINT import_map_launch_round")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT import_map_launch_round")
        conn.execute("RELEASE SAVEPOINT import_map_launch_round")
        raise
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Export or import a validated daily map launch round.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--db", type=Path, required=True)
    export_parser.add_argument("--date", required=True)
    export_parser.add_argument("--output", type=Path, required=True)
    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("--db", type=Path, required=True)
    import_parser.add_argument("--input", type=Path, required=True)
    import_parser.add_argument("--target-date")
    import_parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.command == "export":
        with connect(args.db) as conn:
            payload = export_round(conn, args.date)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"output": str(args.output), "date": args.date}, sort_keys=True))
        return

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    with connect(args.db) as conn:
        daily_map_game.initialize_database(conn)
        result = import_round(conn, payload, target_date=args.target_date, dry_run=args.dry_run)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

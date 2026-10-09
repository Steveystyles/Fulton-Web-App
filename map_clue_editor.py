"""Admin-only, copy-on-write corrections for published Map clue ladders."""

from __future__ import annotations

import secrets
import sqlite3
from typing import Any

import daily_map_game


MAX_CORRECTION_REASON_LENGTH = 240


def initialize_corrections(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS map_clue_corrections (
            id INTEGER PRIMARY KEY,
            puzzle_date TEXT NOT NULL,
            level_slug TEXT NOT NULL,
            old_place_id INTEGER NOT NULL REFERENCES map_place_pool(id),
            new_place_id INTEGER NOT NULL UNIQUE REFERENCES map_place_pool(id),
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )


def correction_feedback_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Turn saved human corrections into negative examples, never unverified approvals."""
    initialize_corrections(conn)
    rows = conn.execute(
        """
        SELECT corrections.id, corrections.reason,
               original.canonical_name, original.place_type,
               original.clue_text AS old_hard,
               original.medium_clue_text AS old_medium,
               original.easy_clue_text AS old_easy,
               revised.clue_text AS new_hard,
               revised.medium_clue_text AS new_medium,
               revised.easy_clue_text AS new_easy
        FROM map_clue_corrections AS corrections
        JOIN map_place_pool AS original ON original.id = corrections.old_place_id
        JOIN map_place_pool AS revised ON revised.id = corrections.new_place_id
        ORDER BY corrections.id
        """
    ).fetchall()
    feedback: list[dict[str, Any]] = []
    for row in rows:
        old = {level: str(row[f"old_{level}"]) for level in ("hard", "medium", "easy")}
        revised = {level: str(row[f"new_{level}"]) for level in ("hard", "medium", "easy")}
        changed = [level for level in old if old[level] != revised[level]]
        if not changed:
            continue
        reason = str(row["reason"])
        reviews = {
            level: {
                "level": level,
                "clue": old[level],
                "pass_fail": "fail",
                "reason": reason,
                "better_direction": revised[level],
            }
            for level in changed
        }
        item: dict[str, Any] = {
            "candidate_id": f"admin-map-clue-correction-{row['id']}",
            "place": str(row["canonical_name"]),
            "type": str(row["place_type"]),
            "clues": old,
            "clue_scores": {level: "fail" for level in changed},
            "clue_reviews": reviews,
        }
        if "hard" in reviews:
            item["hard_review"] = {
                **reviews["hard"],
                "fact": "",
            }
        feedback.append(item)
    return feedback


def admin_puzzle_clues(conn: sqlite3.Connection, puzzle_date: str) -> dict[str, Any]:
    """Return complete clue ladders to a caller that has checked admin access."""
    puzzle_date = daily_map_game.valid_game_date(puzzle_date)
    rows = conn.execute(
        """
        SELECT levels.level_slug, levels.place_id, places.canonical_name,
               places.clue_text, places.medium_clue_text, places.easy_clue_text,
               places.reveal_text
        FROM daily_map_puzzles AS puzzles
        JOIN daily_map_levels AS levels ON levels.puzzle_id = puzzles.id
        JOIN map_place_pool AS places ON places.id = levels.place_id
        WHERE puzzles.puzzle_date = ? AND puzzles.status = 'published'
        ORDER BY CASE levels.level_slug
            WHEN 'easy' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END
        """,
        (puzzle_date,),
    ).fetchall()
    return {
        "date": puzzle_date,
        "levels": [
            {
                "level": row["level_slug"],
                "placeId": row["place_id"],
                "answer": row["canonical_name"],
                "hard": row["clue_text"],
                "medium": row["medium_clue_text"],
                "easy": row["easy_clue_text"],
                "reveal": row["reveal_text"],
            }
            for row in rows
        ],
    }


def revise_published_clues(
    conn: sqlite3.Connection,
    *,
    puzzle_date: str,
    level_slug: str,
    expected_place_id: int,
    clues: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    """Version a place row so a live clue fix does not alter earlier uses."""
    puzzle_date = daily_map_game.valid_game_date(puzzle_date)
    if level_slug not in daily_map_game.DIFFICULTIES:
        raise ValueError("Choose an easy, medium, or hard map level.")
    if type(expected_place_id) is not int or expected_place_id < 1:
        raise ValueError("A valid current place ID is required.")
    if not isinstance(clues, dict):
        raise ValueError("Provide all four clue texts.")
    if not isinstance(reason, str) or not 12 <= len(reason.strip()) <= MAX_CORRECTION_REASON_LENGTH:
        raise ValueError("Explain what was wrong with the original clue in 12 to 240 characters.")
    reason = reason.strip()
    cleaned: dict[str, str] = {}
    for field in daily_map_game.MAP_CLUE_REQUIRED_FIELDS:
        value = clues.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field.capitalize()} text is required.")
        value = value.strip()
        if len(value) > daily_map_game.MAP_CLUE_TEXT_LIMITS[field]:
            raise ValueError(f"{field.capitalize()} text is too long.")
        cleaned[field] = value

    level = conn.execute(
        """
        SELECT levels.id, levels.place_id, places.*
        FROM daily_map_puzzles AS puzzles
        JOIN daily_map_levels AS levels ON levels.puzzle_id = puzzles.id
        JOIN map_place_pool AS places ON places.id = levels.place_id
        WHERE puzzles.puzzle_date = ? AND puzzles.status = 'published'
          AND levels.level_slug = ?
        """,
        (puzzle_date, level_slug),
    ).fetchone()
    if level is None:
        raise LookupError("No published map level exists for that date.")
    if level["place_id"] != expected_place_id:
        raise RuntimeError("This map level changed. Reload its clues before saving.")
    place = dict(level)
    place["acceptable_aliases"] = daily_map_game.split_list_text(place["acceptable_aliases"])
    if all(cleaned[field] == str(place[source]) for field, source in (
        ("hard", "clue_text"), ("medium", "medium_clue_text"),
        ("easy", "easy_clue_text"), ("reveal", "reveal_text"),
    )):
        raise ValueError("Change at least one clue or the answer reveal before saving.")
    if any(daily_map_game.clue_contains_answer(cleaned[field], place) for field in ("hard", "medium", "easy")):
        raise ValueError("A playable clue reveals the answer or an alias.")

    inserted = conn.execute(
        """
        INSERT INTO map_place_pool (
            slug, canonical_name, country_code, country_name, continent, admin1,
            place_type, difficulty, lat, lng, coordinate_precision,
            suggested_map_zoom, map_search_anchors_json, clue_text,
            medium_clue_text, easy_clue_text, reveal_text, acceptable_aliases,
            nearby_context, verified_facts_json, sources_json,
            coordinate_source_name, coordinate_source_url, avoid_in_clues,
            deconflict_group, fact_stability, review_status, review_notes,
            reviewed_on, clue_generation_source, clue_profile_hash,
            clue_critic_mode, validation_grade, validation_reasoning,
            scoring_radius_m, active, cooldown_until, created_at
        )
        SELECT
            ?, canonical_name, country_code, country_name, continent, admin1,
            place_type, difficulty, lat, lng, coordinate_precision,
            suggested_map_zoom, map_search_anchors_json, ?, ?, ?, ?, acceptable_aliases,
            nearby_context, '[]', sources_json,
            coordinate_source_name, coordinate_source_url, avoid_in_clues,
            deconflict_group, fact_stability, 'approved',
            'Admin revised published clue text; prior verified facts do not apply to this revision.',
            ?, 'admin-edit', '', 'admin-review', NULL,
            'Published clue wording revised by an admin.',
            scoring_radius_m, 0, cooldown_until, ?
        FROM map_place_pool WHERE id = ?
        """,
        (
            f"{level['slug']}-revision-{secrets.token_hex(6)}",
            cleaned["hard"],
            cleaned["medium"],
            cleaned["easy"],
            cleaned["reveal"],
            daily_map_game.utc_now(),
            daily_map_game.utc_now(),
            expected_place_id,
        ),
    )
    # The corrected live copy is not AI-reviewed for future selection, while the
    # superseded wording must not drift back into the playable place pool.
    conn.execute("UPDATE map_place_pool SET active = 0 WHERE id = ?", (expected_place_id,))
    updated = conn.execute(
        "UPDATE daily_map_levels SET place_id = ? WHERE id = ? AND place_id = ?",
        (inserted.lastrowid, level["id"], expected_place_id),
    )
    if updated.rowcount != 1:
        raise RuntimeError("This map level changed. Reload its clues before saving.")
    initialize_corrections(conn)
    conn.execute(
        """
        INSERT INTO map_clue_corrections (
            puzzle_date, level_slug, old_place_id, new_place_id, reason, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            puzzle_date, level_slug, expected_place_id, inserted.lastrowid,
            reason, daily_map_game.utc_now(),
        ),
    )
    return admin_puzzle_clues(conn, puzzle_date)

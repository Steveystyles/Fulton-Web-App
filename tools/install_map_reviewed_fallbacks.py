from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import daily_map_game


SCHEMA_VERSION = 1
REQUIRED_PLACE_FIELDS = {
    "slug",
    "canonical_name",
    "country_code",
    "difficulty",
    "lat",
    "lng",
    "clue_text",
    "medium_clue_text",
    "easy_clue_text",
    "reveal_text",
    "map_search_anchors_json",
}
RUNTIME_PLACE_FIELDS = {"active", "cooldown_until", "created_at"}


def load_package(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError(f"Reviewed map fallback schemaVersion must be {SCHEMA_VERSION}.")
    entries = payload.get("places")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Reviewed map fallback package must contain places.")
    return entries


def install_seed(conn: sqlite3.Connection, path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "installed": False,
            "reason": "reviewed fallback package is absent",
            "added": [],
            "updated": [],
            "existing": [],
        }

    daily_map_game.initialize_database(conn)
    table_columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(map_place_pool)")
        if str(row[1]) != "id"
    }
    added: list[str] = []
    updated: list[str] = []
    existing: list[str] = []

    for index, entry in enumerate(load_package(path), start=1):
        if not isinstance(entry, dict) or not isinstance(entry.get("place"), dict):
            raise ValueError(f"Reviewed map fallback entry {index} is invalid.")
        place = dict(entry["place"])
        missing = sorted(REQUIRED_PLACE_FIELDS.difference(place))
        if missing:
            raise ValueError(
                f"Reviewed map fallback entry {index} is missing: {', '.join(missing)}"
            )
        slug = str(place["slug"]).strip()
        if not slug:
            raise ValueError(f"Reviewed map fallback entry {index} has no slug.")
        if not daily_map_game.row_has_playable_map_guidance(place):
            raise ValueError(
                f"Reviewed map fallback {place['canonical_name']!r} has no playable "
                "boundary and easy target guidance."
            )
        current = conn.execute(
            "SELECT * FROM map_place_pool WHERE slug = ?",
            (slug,),
        ).fetchone()
        if current is not None:
            synced_columns = [
                column
                for column in place
                if column in table_columns and column not in RUNTIME_PLACE_FIELDS
            ]
            changed_columns = [
                column
                for column in synced_columns
                if current[column] != place[column]
            ]
            if changed_columns:
                assignments = ", ".join(f"{column} = ?" for column in changed_columns)
                conn.execute(
                    f"UPDATE map_place_pool SET {assignments} WHERE id = ?",
                    (*[place[column] for column in changed_columns], current["id"]),
                )
                current = conn.execute(
                    "SELECT * FROM map_place_pool WHERE id = ?",
                    (current["id"],),
                ).fetchone()
                if (
                    current is None
                    or not daily_map_game.row_passes_map_clue_quality(
                        current, enforce_light_tone=False
                    )
                    or not daily_map_game.row_has_playable_map_guidance(current)
                ):
                    raise ValueError(
                        f"Updated reviewed map fallback {place['canonical_name']!r} "
                        "fails the publication gate."
                    )
                updated.append(str(current["canonical_name"]))
            else:
                existing.append(str(current["canonical_name"]))
            continue

        columns = [column for column in place if column in table_columns]
        placeholders = ", ".join("?" for _ in columns)
        conn.execute(
            f"INSERT INTO map_place_pool ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(place[column] for column in columns),
        )
        inserted = conn.execute(
            "SELECT * FROM map_place_pool WHERE slug = ?",
            (slug,),
        ).fetchone()
        if (
            inserted is None
            or not daily_map_game.row_passes_map_clue_quality(
                inserted, enforce_light_tone=False
            )
            or not daily_map_game.row_has_playable_map_guidance(inserted)
        ):
            raise ValueError(
                f"Reviewed map fallback {place['canonical_name']!r} fails the local clue gate."
            )
        added.append(str(inserted["canonical_name"]))

    return {
        "installed": bool(added or updated),
        "reason": "",
        "added": added,
        "updated": updated,
        "existing": existing,
    }

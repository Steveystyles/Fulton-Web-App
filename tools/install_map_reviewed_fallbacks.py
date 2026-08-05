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
            "existing": [],
        }

    daily_map_game.initialize_database(conn)
    table_columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(map_place_pool)")
        if str(row[1]) != "id"
    }
    added: list[str] = []
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
        current = conn.execute(
            "SELECT * FROM map_place_pool WHERE slug = ?",
            (slug,),
        ).fetchone()
        if current is not None:
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
        if inserted is None or not daily_map_game.row_passes_map_clue_quality(inserted):
            raise ValueError(
                f"Reviewed map fallback {place['canonical_name']!r} fails the local clue gate."
            )
        added.append(str(inserted["canonical_name"]))

    return {
        "installed": bool(added),
        "reason": "",
        "added": added,
        "existing": existing,
    }

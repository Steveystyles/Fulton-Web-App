from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import daily_map_game
from tools import map_launch_round


class MapLaunchRoundTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.source = self._database("source.db")
        self.target = self._database("target.db")

    def _database(self, name: str) -> sqlite3.Connection:
        path = Path(self.temp_dir.name) / name
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        daily_map_game.initialize_database(conn)
        self.addCleanup(conn.close)
        return conn

    def _publish_source_round(self) -> None:
        place = self.source.execute(
            "SELECT id FROM map_place_pool WHERE canonical_name = 'London'"
        ).fetchone()
        anchors = [
            {
                "name": "England",
                "lat": 52.3,
                "lng": -1.5,
                "min_hint_count": 1,
                "min_zoom": 4,
                "max_zoom": 9,
                "boundary_kind": "guidance",
                "boundary_min_zoom": 4,
                "boundary": {
                    "type": "Polygon",
                    "coordinates": [[[-3, 50], [1, 50], [1, 54], [-3, 54], [-3, 50]]],
                },
            },
            {
                "name": "London",
                "lat": 51.5074,
                "lng": -0.1278,
                "min_hint_count": 2,
                "min_zoom": 12,
                "max_zoom": 19,
            },
        ]
        self.source.execute(
            """
            UPDATE map_place_pool
            SET medium_clue_text = 'A medium clue in England.',
                easy_clue_text = 'An easy clue in London.',
                reveal_text = 'London',
                map_search_anchors_json = ?
            WHERE id = ?
            """,
            (json.dumps(anchors), place["id"]),
        )
        cursor = self.source.execute(
            """
            INSERT INTO daily_map_puzzles (
                puzzle_date, status, generated_at, published_at
            ) VALUES ('2026-08-04', 'published', 'now', 'now')
            """
        )
        self.source.execute(
            """
            INSERT INTO daily_map_levels (
                puzzle_id, level_slug, place_id, max_points, lambda_km, created_at
            ) VALUES (?, 'easy', ?, 10, 5, 'now')
            """,
            (cursor.lastrowid, place["id"]),
        )
        self.source.commit()

    def test_export_and_import_preserve_validated_round(self) -> None:
        self._publish_source_round()
        payload = map_launch_round.export_round(self.source, "2026-08-04")

        dry_run = map_launch_round.import_round(
            self.target,
            payload,
            target_date="2026-08-05",
            dry_run=True,
        )
        self.assertEqual(dry_run["status"], "validated")
        self.assertIsNone(
            self.target.execute(
                "SELECT id FROM daily_map_puzzles WHERE puzzle_date = '2026-08-05'"
            ).fetchone()
        )

        imported = map_launch_round.import_round(
            self.target,
            payload,
            target_date="2026-08-05",
        )
        self.target.commit()
        self.assertEqual(imported["status"], "published")
        row = self.target.execute(
            """
            SELECT daily_map_puzzles.status, daily_map_levels.max_points,
                   map_place_pool.medium_clue_text
            FROM daily_map_puzzles
            JOIN daily_map_levels ON daily_map_levels.puzzle_id = daily_map_puzzles.id
            JOIN map_place_pool ON map_place_pool.id = daily_map_levels.place_id
            WHERE daily_map_puzzles.puzzle_date = '2026-08-05'
            """
        ).fetchone()
        self.assertEqual(dict(row), {
            "status": "published",
            "max_points": 10,
            "medium_clue_text": "A medium clue in England.",
        })

    def test_import_refuses_to_replace_submitted_round(self) -> None:
        self._publish_source_round()
        payload = map_launch_round.export_round(self.source, "2026-08-04")
        map_launch_round.import_round(self.target, payload)
        self.target.execute(
            "INSERT INTO users VALUES (1, 'user', 'hash', 'user', 'now', 'now')"
        )
        level_id = self.target.execute("SELECT id FROM daily_map_levels").fetchone()[0]
        self.target.execute(
            """
            INSERT INTO daily_map_guesses (
                user_id, level_id, guessed_lat, guessed_lng, revealed_hint_count,
                distance_m, score, band, completed_at, created_at, updated_at
            ) VALUES (1, ?, 0, 0, 0, 0, 10, 'Correct', 'now', 'now', 'now')
            """,
            (level_id,),
        )
        self.target.commit()

        with self.assertRaisesRegex(ValueError, "submitted guesses"):
            map_launch_round.import_round(self.target, payload)

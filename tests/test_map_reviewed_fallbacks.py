from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

import daily_map_game
from tools import install_map_reviewed_fallbacks


PROJECT_DIR = Path(__file__).resolve().parents[1]
PACKAGE_PATH = PROJECT_DIR / "deploy" / "map-reviewed-fallbacks.json"


class MapReviewedFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        daily_map_game.initialize_database(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_reviewed_fallback_package_installs_quality_gated_places(self) -> None:
        entries = install_map_reviewed_fallbacks.load_package(PACKAGE_PATH)
        expected_names = {entry["place"]["canonical_name"] for entry in entries}
        result = install_map_reviewed_fallbacks.install_seed(self.conn, PACKAGE_PATH)

        self.assertEqual(set(result["added"]), expected_names)
        rows = self.conn.execute(
            f"SELECT * FROM map_place_pool WHERE canonical_name IN "
            f"({', '.join('?' for _ in expected_names)})",
            tuple(expected_names),
        ).fetchall()
        self.assertEqual(len(rows), len(expected_names))
        self.assertTrue(all(daily_map_game.row_passes_map_clue_quality(row) for row in rows))
        self.assertTrue(all(daily_map_game.row_has_playable_map_guidance(row) for row in rows))

    def test_reviewed_fallback_install_is_idempotent(self) -> None:
        expected_count = len(install_map_reviewed_fallbacks.load_package(PACKAGE_PATH))
        install_map_reviewed_fallbacks.install_seed(self.conn, PACKAGE_PATH)

        result = install_map_reviewed_fallbacks.install_seed(self.conn, PACKAGE_PATH)

        self.assertEqual(result["added"], [])
        self.assertEqual(result["updated"], [])
        self.assertEqual(len(result["existing"]), expected_count)

    def test_reviewed_fallback_install_repairs_existing_guidance(self) -> None:
        install_map_reviewed_fallbacks.install_seed(self.conn, PACKAGE_PATH)
        self.conn.execute(
            "UPDATE map_place_pool SET map_search_anchors_json = '[]' "
            "WHERE canonical_name = 'Terracotta Army'"
        )

        result = install_map_reviewed_fallbacks.install_seed(self.conn, PACKAGE_PATH)

        self.assertEqual(result["updated"], ["Terracotta Army"])
        row = self.conn.execute(
            "SELECT * FROM map_place_pool WHERE canonical_name = 'Terracotta Army'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertTrue(daily_map_game.row_has_playable_map_guidance(row))


if __name__ == "__main__":
    unittest.main()

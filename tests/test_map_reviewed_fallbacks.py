from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.assertTrue(all(
            daily_map_game.row_passes_map_clue_quality(row, enforce_light_tone=False)
            for row in rows
        ))
        canterbury = next(row for row in rows if row["canonical_name"] == "Canterbury Cathedral")
        self.assertFalse(daily_map_game.row_passes_map_clue_quality(canterbury))
        self.assertTrue(all(daily_map_game.row_has_playable_map_guidance(row) for row in rows))

    def test_reviewed_fallback_install_is_idempotent(self) -> None:
        expected_count = len(install_map_reviewed_fallbacks.load_package(PACKAGE_PATH))
        install_map_reviewed_fallbacks.install_seed(self.conn, PACKAGE_PATH)

        result = install_map_reviewed_fallbacks.install_seed(self.conn, PACKAGE_PATH)

        self.assertEqual(result["added"], [])
        self.assertEqual(result["updated"], [])
        self.assertEqual(len(result["existing"]), expected_count)

    def test_fallback_selection_skips_legacy_victim_harm_hook(self) -> None:
        self.conn.execute("UPDATE map_place_pool SET active = 0")
        install_map_reviewed_fallbacks.install_seed(self.conn, PACKAGE_PATH)
        self.conn.execute(
            "UPDATE map_place_pool SET active = CASE WHEN canonical_name IN "
            "('Canterbury Cathedral', 'Terracotta Army') THEN 1 ELSE 0 END"
        )

        selected = daily_map_game.select_daily_place(self.conn, "2026-10-28")

        self.assertIsNotNone(selected)
        self.assertEqual(selected["canonical_name"], "Terracotta Army")

    def test_fallback_ranks_stadiums_by_story_quality_like_other_places(self) -> None:
        self.conn.execute("UPDATE map_place_pool SET active = 0")
        install_map_reviewed_fallbacks.install_seed(self.conn, PACKAGE_PATH)
        self.conn.execute(
            "UPDATE map_place_pool SET active = CASE WHEN canonical_name IN "
            "('Wembley Stadium', 'Terracotta Army') THEN 1 ELSE 0 END"
        )
        def quality(row, _profile):
            return {
                "persuadingFactCount": 3,
                "score": 90 if row["place_type"] == "stadium" else 50,
                "categories": ["place-owned story"],
                "validationGrade": 0.9,
            }

        with patch.object(daily_map_game, "map_place_selection_profile", side_effect=quality):
            preferred = daily_map_game.select_daily_place(self.conn, "2026-10-28")
        self.assertIsNotNone(preferred)
        self.assertEqual(preferred["canonical_name"], "Wembley Stadium")

        def other_place_is_stronger(row, _profile):
            result = quality(row, _profile)
            result["score"] = 90 if row["place_type"] != "stadium" else 50
            return result

        with patch.object(daily_map_game, "map_place_selection_profile",
                          side_effect=other_place_is_stronger):
            preferred = daily_map_game.select_daily_place(self.conn, "2026-10-28")
        self.assertEqual(preferred["canonical_name"], "Terracotta Army")

        self.conn.execute(
            "UPDATE map_place_pool SET active = 0 WHERE canonical_name = 'Terracotta Army'"
        )
        only_place = daily_map_game.select_daily_place(self.conn, "2026-10-28")
        self.assertIsNotNone(only_place)
        self.assertEqual(only_place["canonical_name"], "Wembley Stadium")

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

from __future__ import annotations

import importlib
import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import daily_map_game

importer = importlib.import_module("tools.import_map_place_bank")
profile_builder = importlib.import_module("tools.build_map_learning_profile")
exporter = importlib.import_module("tools.export_map_clue_training_data")
failure_log = importlib.import_module("tools.map_clue_failure_log")
refresh = importlib.import_module("tools.refresh_map_learning_profile")
training_store = importlib.import_module("tools.training_data_store")


class MapClueLearningTests(unittest.TestCase):
    def test_import_place_bank_loads_curated_clue_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "fultons.db"
            csv_path = root / "places.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "canonical_name",
                        "place_type",
                        "country_code",
                        "country_name",
                        "continent",
                        "admin1",
                        "lat",
                        "lng",
                        "coordinate_precision",
                        "suggested_map_zoom",
                        "answer_radius_km",
                        "difficulty",
                        "acceptable_aliases",
                        "nearby_context",
                        "verified_fact_1",
                        "verified_fact_2",
                        "verified_fact_3",
                        "landmark_or_visual_hook",
                        "avoid_in_clues",
                        "source_1_name",
                        "source_1_url",
                        "source_2_name",
                        "source_2_url",
                        "coordinate_source_name",
                        "coordinate_source_url",
                        "example_hard_clue",
                        "example_medium_clue",
                        "example_easy_clue",
                        "reveal_text",
                        "deconflict_group",
                        "fact_stability",
                        "review_status",
                        "review_notes",
                        "reviewed_on",
                        "validation_grade",
                        "validation_reasoning",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "canonical_name": "Test Harbour",
                        "place_type": "city",
                        "country_code": "GB",
                        "country_name": "United Kingdom",
                        "continent": "Europe",
                        "admin1": "Scotland",
                        "lat": "55.1",
                        "lng": "-4.1",
                        "coordinate_precision": "city centre",
                        "suggested_map_zoom": "11",
                        "answer_radius_km": "4.5",
                        "difficulty": "medium",
                        "nearby_context": "estuary",
                        "verified_fact_1": "Historic harbour",
                        "verified_fact_2": "Old town",
                        "landmark_or_visual_hook": "A tidal river mouth",
                        "source_1_name": "Source",
                        "source_1_url": "https://example.com",
                        "coordinate_source_name": "Coordinate Source",
                        "coordinate_source_url": "https://example.com/coords",
                        "example_hard_clue": "A harbour town with an old quay.",
                        "example_medium_clue": "Look in Scotland for the old quay town.",
                        "example_easy_clue": "Find the town beside the tidal river mouth.",
                        "reveal_text": "Test Harbour is a Scottish harbour town.",
                        "deconflict_group": "test-harbour",
                        "fact_stability": "high",
                        "review_status": "approved",
                        "review_notes": "Reviewed",
                        "reviewed_on": "2026-07-16",
                        "validation_grade": "8",
                        "validation_reasoning": "Good test row.",
                    }
                )

            result = importer.import_place_bank(csv_path, db_path)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM map_place_pool WHERE canonical_name = 'Test Harbour'"
            ).fetchone()
            conn.close()

        self.assertEqual(result["imported"], 1)
        self.assertIsNotNone(row)
        self.assertEqual(row["place_type"], "city")
        self.assertEqual(row["medium_clue_text"], "Look in Scotland for the old quay town.")
        self.assertIn("Historic harbour", row["verified_facts_json"])
        self.assertEqual(row["scoring_radius_m"], 4500)
        self.assertEqual(row["suggested_map_zoom"], 11)
        self.assertEqual(row["validation_grade"], 8)
        self.assertEqual(row["coordinate_source_url"], "https://example.com/coords")

    def test_import_place_bank_skips_low_grade_and_hold_rows_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "fultons.db"
            csv_path = root / "places.csv"
            fieldnames = [
                "row_id",
                "canonical_name",
                "place_type",
                "country_code",
                "country_name",
                "admin1",
                "lat",
                "lng",
                "difficulty",
                "verified_fact_1",
                "landmark_or_visual_hook",
                "source_1_name",
                "source_1_url",
                "example_medium_clue",
                "reveal_text",
                "review_status",
                "validation_grade",
            ]
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(
                    {
                        "row_id": "good",
                        "canonical_name": "Good Place",
                        "place_type": "city",
                        "country_code": "GB",
                        "country_name": "United Kingdom",
                        "admin1": "Scotland",
                        "lat": "55",
                        "lng": "-4",
                        "difficulty": "easy",
                        "verified_fact_1": "A verified good fact.",
                        "landmark_or_visual_hook": "A clear river bend.",
                        "source_1_name": "Source",
                        "source_1_url": "https://example.com/good",
                        "example_medium_clue": "Look in Scotland for a clear river bend.",
                        "reveal_text": "Good Place is a test place.",
                        "review_status": "approved",
                        "validation_grade": "8",
                    }
                )
                writer.writerow(
                    {
                        "row_id": "low",
                        "canonical_name": "Low Grade Place",
                        "place_type": "city",
                        "country_code": "GB",
                        "country_name": "United Kingdom",
                        "admin1": "Scotland",
                        "lat": "56",
                        "lng": "-4",
                        "difficulty": "easy",
                        "verified_fact_1": "A weak but valid fact.",
                        "landmark_or_visual_hook": "A generic town centre.",
                        "source_1_name": "Source",
                        "source_1_url": "https://example.com/low",
                        "example_medium_clue": "Look in Scotland for this town.",
                        "reveal_text": "Low Grade Place is a test place.",
                        "review_status": "approved",
                        "validation_grade": "6",
                    }
                )
                writer.writerow(
                    {
                        "row_id": "hold",
                        "canonical_name": "Hold Place",
                        "place_type": "city",
                        "country_code": "GB",
                        "country_name": "United Kingdom",
                        "admin1": "Scotland",
                        "lat": "57",
                        "lng": "-4",
                        "difficulty": "easy",
                        "verified_fact_1": "A valid fact.",
                        "landmark_or_visual_hook": "A visible harbour.",
                        "source_1_name": "Source",
                        "source_1_url": "https://example.com/hold",
                        "example_medium_clue": "Locate the target near 57 degrees north in ISO country code GB.",
                        "reveal_text": "Hold Place is a test place.",
                        "review_status": "approved",
                        "validation_grade": "8",
                    }
                )

            result = importer.import_place_bank(csv_path, db_path)
            conn = sqlite3.connect(db_path)
            count = conn.execute(
                "SELECT COUNT(*) FROM map_place_pool WHERE canonical_name IN ('Good Place', 'Low Grade Place', 'Hold Place')"
            ).fetchone()[0]
            conn.close()

        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["ready"], 1)
        self.assertEqual(result["review"], 2)
        self.assertEqual(result["hold"], 0)
        self.assertEqual(result["skipped"], 2)
        self.assertEqual(count, 1)

    def test_import_place_bank_reports_draft_rows_as_review_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "fultons.db"
            csv_path = root / "places.csv"
            fieldnames = [
                "canonical_name",
                "place_type",
                "country_code",
                "country_name",
                "admin1",
                "lat",
                "lng",
                "difficulty",
                "verified_fact_1",
                "landmark_or_visual_hook",
                "source_1_name",
                "source_1_url",
                "example_hard_clue",
                "example_medium_clue",
                "example_easy_clue",
                "reveal_text",
                "review_status",
                "validation_grade",
            ]
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(
                    {
                        "canonical_name": "Draft Place",
                        "place_type": "city",
                        "country_code": "GB",
                        "country_name": "United Kingdom",
                        "admin1": "England",
                        "lat": "53",
                        "lng": "-2",
                        "difficulty": "medium",
                        "verified_fact_1": "Draft Place has a valid but unreviewed fact.",
                        "landmark_or_visual_hook": "a visible civic tower",
                        "source_1_name": "Source",
                        "source_1_url": "https://example.com/draft",
                        "example_hard_clue": "A civic tower gives this unreviewed row a possible hook.",
                        "example_medium_clue": "Local museum collections may support a stronger second clue.",
                        "example_easy_clue": "A visible civic tower anchors the map pin.",
                        "reveal_text": "Draft Place is a review-only test row.",
                        "review_status": "draft",
                        "validation_grade": "7",
                    }
                )

            result = importer.import_place_bank(csv_path, db_path)

        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["review"], 1)
        self.assertEqual(result["hold"], 0)
        self.assertFalse(result["errors"])
        self.assertTrue(any(item["tier"] == "review" for item in result["warnings"]))

    def test_import_place_bank_allows_location_qualified_alias_with_comma(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "fultons.db"
            csv_path = root / "places.csv"
            fieldnames = [
                "canonical_name",
                "place_type",
                "country_code",
                "country_name",
                "admin1",
                "lat",
                "lng",
                "difficulty",
                "acceptable_aliases",
                "verified_fact_1",
                "landmark_or_visual_hook",
                "source_1_name",
                "source_1_url",
                "example_hard_clue",
                "example_medium_clue",
                "example_easy_clue",
                "reveal_text",
                "review_status",
                "validation_grade",
            ]
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(
                    {
                        "canonical_name": "Horseshoe Bend",
                        "place_type": "natural_landmark",
                        "country_code": "US",
                        "country_name": "United States",
                        "admin1": "Arizona",
                        "lat": "36.8792",
                        "lng": "-111.5104",
                        "difficulty": "easy",
                        "acceptable_aliases": "Horseshoe Bend, Arizona",
                        "verified_fact_1": "The green river wraps around a massive red-rock butte.",
                        "landmark_or_visual_hook": "a near-circular river meander",
                        "source_1_name": "Source",
                        "source_1_url": "https://example.com/bend",
                        "example_hard_clue": "A dam upstream changed flow through this river meander.",
                        "example_medium_clue": "A desert trail reaches a fenced overlook above sandstone.",
                        "example_easy_clue": "The river wraps around a massive red-rock butte.",
                        "reveal_text": "Horseshoe Bend matches the clues through its river meander.",
                        "review_status": "approved",
                        "validation_grade": "9",
                    }
                )

            result = importer.import_place_bank(csv_path, db_path)

        self.assertEqual(result["imported"], 1)
        self.assertFalse(result["warnings"])
        self.assertFalse(result["errors"])

    def test_build_map_learning_profile_summarizes_negative_patterns(self) -> None:
        records = [
            {
                "feedback_to_generator": "The ladder is repetitive and repeats the same information.",
                "metadata": {"place_type": "city", "difficulty": "medium"},
            },
            {
                "failure_reason": "The clue reveals the answer name too early.",
                "metadata": {"place_type": "landmark", "difficulty": "hard"},
            },
        ]

        profile = profile_builder.build_profile(records, source=Path("negative.jsonl"))

        self.assertEqual(profile["negative_count"], 2)
        self.assertEqual(profile["pattern_counts"]["repetitive_ladder"], 1)
        self.assertEqual(profile["pattern_counts"]["answer_leak"], 1)
        self.assertIn("global", profile["feedback_by_slot"])
        self.assertIn("city/medium", profile["feedback_by_slot"])

    def test_build_map_learning_profile_uses_failure_categories(self) -> None:
        records = [
            {
                "feedback_to_generator": ["Try a different clue."],
                "failure_categories": ["broad_multi_site_target", "unsupported_fact"],
                "metadata": {"place_type": "archaeological_site", "difficulty": "medium"},
            }
        ]

        profile = profile_builder.build_profile(records, source=Path("failure_log.jsonl"))

        self.assertEqual(profile["pattern_counts"]["broad_multi_site_target"], 1)
        self.assertEqual(profile["pattern_counts"]["unsupported_fact"], 1)
        self.assertTrue(
            any(
                "Avoid broad serial or multi-site" in item
                for item in profile["feedback_by_slot"]["archaeological_site/medium"]
            )
        )
        self.assertTrue(
            any(
                "Use only details supported" in item
                for item in profile["feedback_by_slot"]["archaeological_site/medium"]
            )
        )

    def test_build_map_learning_profile_keeps_broad_geography_as_location_based(self) -> None:
        records = [
            {
                "feedback_to_generator": "Do not make clues mainly about where the place is, what it is near, or broad geography.",
                "metadata": {"place_type": "city", "difficulty": "easy"},
            }
        ]

        profile = profile_builder.build_profile(records, source=Path("negative.jsonl"))

        self.assertEqual(profile["pattern_counts"]["location_based"], 1)
        self.assertNotIn("broad_multi_site_target", profile["pattern_counts"])

    def test_failure_log_classifier_keeps_broad_geography_as_location_based(self) -> None:
        categories = failure_log.classify_failure_reasons(
            ["One or more playable clues are mainly about location, proximity, or broad geography."]
        )

        self.assertIn("location_based", categories)
        self.assertNotIn("broad_multi_site_target", categories)

    def test_export_map_clue_training_data_writes_reviewed_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "fultons.db"
            out_dir = root / "training"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL)")
            daily_map_game.initialize_database(conn)
            conn.execute("UPDATE map_place_pool SET active = 0")
            place_id = conn.execute(
                "SELECT id FROM map_place_pool WHERE canonical_name = 'Cape Town'"
            ).fetchone()["id"]
            conn.execute(
                """
                UPDATE map_place_pool
                SET verified_facts_json = ?,
                    nearby_context = ?,
                    active = 1
                WHERE id = ?
                """,
                (
                    json.dumps(
                        [
                            "Nelson Mandela made his first public speech after 27 years of imprisonment from City Hall.",
                            "This South African legislative capital sits beneath Table Mountain.",
                            "The City Bowl lies between Table Mountain and the Atlantic waterfront.",
                        ]
                    ),
                    "City Bowl, Table Mountain, Atlantic waterfront",
                    place_id,
                ),
            )
            daily_map_game.save_reviewed_clue_ladder(
                conn,
                place_id=place_id,
                clue_ladder={
                    "hard": "Nelson Mandela made his first public speech after 27 years of imprisonment from City Hall here.",
                    "medium": "This South African legislative capital sits beneath Table Mountain.",
                    "easy": "Work within the City Bowl between Table Mountain and the Atlantic waterfront.",
                    "reveal": "Cape Town links Mandela's City Hall speech with Table Mountain and the City Bowl.",
                },
            )
            conn.execute(
                "UPDATE map_place_pool SET review_status = 'rejected', review_notes = 'Clues repeat the same information.' WHERE canonical_name = 'Bath'"
            )
            conn.commit()
            conn.close()

            with patch.object(exporter.daily_map_game, "initialize_database", return_value=None):
                result = exporter.export_map_clue_training_data(
                    db_path,
                    out_dir,
                    eval_fraction=0,
                    include_seed_negatives=False,
                )
            train_lines = result.train_path.read_text(encoding="utf-8").splitlines()
            negative_lines = result.negative_path.read_text(encoding="utf-8").splitlines()

        self.assertGreaterEqual(result.approved_count, 1)
        self.assertEqual(result.negative_count, 1)
        self.assertTrue(any("Cape Town" in line for line in train_lines))
        negative = json.loads(negative_lines[0])
        self.assertEqual(negative["metadata"]["place"], "Bath")

    def test_export_map_clue_training_data_keeps_inactive_rejected_rows_as_negatives(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "fultons.db"
            out_dir = root / "training"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL)")
            daily_map_game.initialize_database(conn)
            conn.execute("UPDATE map_place_pool SET active = 0")
            conn.execute(
                "UPDATE map_place_pool SET active = 0, review_status = 'approved', review_notes = ''"
            )
            conn.execute(
                """
                UPDATE map_place_pool
                SET active = 0,
                    review_status = 'rejected',
                    review_notes = 'Rejected because it is a broad multi-site target.'
                WHERE canonical_name = 'Bath'
                """
            )
            conn.commit()
            conn.close()

            result = exporter.export_map_clue_training_data(
                db_path,
                out_dir,
                eval_fraction=0,
                include_seed_negatives=False,
            )
            negative_lines = result.negative_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(result.approved_count, 0)
        self.assertEqual(result.negative_count, 1)
        negative = json.loads(negative_lines[0])
        self.assertEqual(negative["metadata"]["place"], "Bath")
        self.assertFalse(negative["metadata"]["active"])

    def test_export_map_clue_training_data_holds_out_eval_and_seeds_negatives(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "fultons.db"
            out_dir = root / "training"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL)")
            daily_map_game.initialize_database(conn)
            conn.execute(
                """
                UPDATE map_place_pool
                SET active = 1,
                    review_status = 'approved',
                    verified_facts_json = ?,
                    nearby_context = 'City Bowl, Table Mountain, Atlantic waterfront',
                    clue_text = 'Nelson Mandela made his first public speech after 27 years of imprisonment from City Hall here.',
                    medium_clue_text = 'This South African legislative capital sits beneath Table Mountain.',
                    easy_clue_text = 'Work within the City Bowl between Table Mountain and the Atlantic waterfront.',
                    reveal_text = 'Cape Town links Mandela''s City Hall speech with Table Mountain and the City Bowl.'
                WHERE canonical_name = 'Cape Town'
                """,
                (
                    json.dumps(
                        [
                            "Nelson Mandela made his first public speech after 27 years of imprisonment from City Hall.",
                            "This South African legislative capital sits beneath Table Mountain.",
                            "The City Bowl lies between Table Mountain and the Atlantic waterfront.",
                        ]
                    ),
                ),
            )
            conn.execute(
                """
                UPDATE map_place_pool
                SET active = 1,
                    review_status = 'approved',
                    verified_facts_json = ?,
                    nearby_context = 'Bath Abbey, Pulteney Bridge, city centre, Somerset, England',
                    clue_text = 'Jane Austen set two novels partly here after living in the spa city with her family.',
                    medium_clue_text = 'This English spa city lies in Somerset west of London.',
                    easy_clue_text = 'Search the city centre between the abbey and Georgian Pulteney Bridge.',
                    reveal_text = 'Bath links Jane Austen, Somerset spa culture, its abbey, and Pulteney Bridge.'
                WHERE canonical_name = 'Bath'
                """,
                (
                    json.dumps(
                        [
                            "Jane Austen set two novels partly here after living in the spa city with her family.",
                            "This English spa city lies in Somerset west of London.",
                            "The abbey and Georgian Pulteney Bridge stand in the compact city centre.",
                        ]
                    ),
                ),
            )
            conn.commit()
            conn.close()

            with patch.object(exporter.daily_map_game, "initialize_database", return_value=None):
                result = exporter.export_map_clue_training_data(
                    db_path,
                    out_dir,
                    eval_fraction=0.2,
                )
            negative_lines = result.negative_path.read_text(encoding="utf-8").splitlines()
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

        self.assertGreater(result.train_count, 0)
        self.assertGreater(result.eval_count, 0)
        self.assertEqual(result.positive_count, result.train_count + result.eval_count)
        self.assertGreaterEqual(result.negative_count, 5)
        self.assertTrue(any("seeded_map_clue_anti_pattern" in line for line in negative_lines))
        self.assertEqual(manifest["format"]["train"], "OpenAI chat fine-tuning JSONL with messages")
        self.assertIn("quality_excluded_count", manifest)

    def test_export_map_clue_training_data_moves_quality_failures_to_negative_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "fultons.db"
            out_dir = root / "training"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL)")
            daily_map_game.initialize_database(conn)
            conn.execute("UPDATE map_place_pool SET active = 0")
            conn.execute(
                """
                UPDATE map_place_pool
                SET active = 1,
                    review_status = 'approved',
                    clue_text = 'In Gulf of Guinea, its wider national-map setting is north of another mapped urban centre.',
                    medium_clue_text = 'Look within the wider national-map setting for one of the country''s mapped urban centres.',
                    easy_clue_text = 'Find the city at 5.354, -4.002 using its time zone metadata.',
                    reveal_text = 'Abidjan is located at 5.354, -4.002 in the Africa/Abidjan time zone.'
                WHERE canonical_name = 'Cape Town'
                """
            )
            conn.commit()
            conn.close()

            result = exporter.export_map_clue_training_data(
                db_path,
                out_dir,
                eval_fraction=0,
                include_seed_negatives=False,
            )
            negative_lines = result.negative_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(result.approved_count, 1)
        self.assertEqual(result.positive_count, 0)
        self.assertEqual(result.quality_excluded_count, 1)
        self.assertEqual(result.train_count, 0)
        self.assertTrue(any("map_clue_quality_gate" in line for line in negative_lines))

    def test_refresh_map_learning_profile_builds_valid_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            negative_path = root / "map_clue_negative_fixture.jsonl"
            negative_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "feedback_to_generator": "The ladder is repetitive and repeats the same information.",
                                "metadata": {"place_type": "city", "difficulty": "easy"},
                            }
                        ),
                        json.dumps(
                            {
                                "feedback_to_generator": "The clue reveals the answer name too early.",
                                "metadata": {"place_type": "landmark", "difficulty": "hard"},
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            profile = refresh.build_candidate_profile(negative_files=[negative_path])
            output_path = refresh.write_candidate_profile(profile, root)
            latest_path = root / "map_learning_profile_latest.json"
            self.assertTrue(output_path.exists())
            self.assertTrue(latest_path.exists())
            latest_profile = json.loads(latest_path.read_text(encoding="utf-8"))

        self.assertTrue(profile["validation"]["passed"])
        self.assertTrue(latest_profile["validation"]["passed"])
        self.assertEqual(profile["negative_count"], 2)
        self.assertIn("MAP_LEARNING_PROFILE_PATH", profile["generator_env_var"])

    def test_refresh_map_learning_profile_includes_structured_gold_ladders(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            negative_path = root / "map_clue_negative_fixture.jsonl"
            negative_path.write_text(
                json.dumps(
                    {
                        "feedback_to_generator": "The clue is generic.",
                        "metadata": {"place_type": "stadium", "difficulty": "medium"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            gold_path = root / "gold.json"
            gold_path.write_text(
                json.dumps(
                    {
                        "examples": [
                            {
                                "example_id": "gold-1",
                                "place_type": "stadium",
                                "clue_ladder": {
                                    "hard": "Hard clue.",
                                    "medium": "Medium clue.",
                                    "easy": "Easy clue.",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            profile = refresh.build_candidate_profile(
                negative_files=[negative_path],
                gold_examples_file=gold_path,
            )

        self.assertEqual(profile["approved_ladders"][0]["example_id"], "gold-1")
        self.assertEqual(profile["source_gold_examples_file"], str(gold_path))

    def test_clean_human_pass_becomes_approved_ladder_but_qualified_pass_does_not(self) -> None:
        clean = {
            "place": "Clean Cathedral",
            "candidate_id": "42",
            "type": "cathedral",
            "your_score": "pass",
            "notes": "",
            "overall_review": {"pass_fail": "pass", "reason": ""},
            "clues": {
                "hard": "A specific event happened inside this building.",
                "medium": "A named writer connected fictional travellers with this shrine.",
                "easy": "Find its tower in the old city centre.",
            },
            "clue_reviews": {
                level: {
                    "pass_fail": "pass",
                    "reason": "",
                }
                for level in ("hard", "medium", "easy")
            },
        }
        qualified = json.loads(json.dumps(clean))
        qualified["place"] = "Qualified Cathedral"
        qualified["clue_reviews"]["medium"]["reason"] = "The fiction is unclear."

        approved = refresh.clean_human_approved_examples_from_rows([clean, qualified])

        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0]["place"], "Clean Cathedral")
        self.assertTrue(training_store.map_place_review_is_clean_approval(clean))
        self.assertFalse(training_store.map_place_review_is_clean_approval(qualified))

        failed = json.loads(json.dumps(clean))
        failed["place"] = "Failed Old Town"
        failed["your_score"] = "fail"
        failed["overall_review"]["pass_fail"] = "fail"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / training_store.MAP_PLACE_REVIEW_FEEDBACK_ALL
            path.write_text(json.dumps({"row": failed}) + "\n", encoding="utf-8")
            failed_names = training_store.failed_map_place_review_names([path])

        self.assertEqual(failed_names, {"failed old town"})

    def test_refresh_map_learning_profile_reads_failure_log_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            failure_log_path = root / "map_clue_failure_log.jsonl"
            failure_log.append_failure_records(
                failure_log_path,
                [
                    {
                        "failure_reason": "Every playable clue must use a concrete known-for hook.",
                        "feedback_to_generator": [
                            "Give each playable clue a distinct known-for hook."
                        ],
                        "failure_categories": ["weak_known_for_hook"],
                        "metadata": {
                            "reason": "map_clue_rewrite_failure",
                            "place": "Test Place",
                            "place_type": "city",
                            "difficulty": "easy",
                            "failure_categories": ["weak_known_for_hook"],
                        },
                    }
                ],
            )

            profile = refresh.build_candidate_profile(
                negative_files=[],
                failure_log_files=[failure_log_path],
            )

        self.assertTrue(profile["validation"]["passed"])
        self.assertEqual(profile["negative_count"], 1)
        self.assertEqual(profile["negative_record_count"], 0)
        self.assertEqual(profile["failure_log_record_count"], 1)
        self.assertIn("weak_known_for_hook", profile["pattern_counts"])
        self.assertIn("city/easy", profile["feedback_by_slot"])


if __name__ == "__main__":
    unittest.main()

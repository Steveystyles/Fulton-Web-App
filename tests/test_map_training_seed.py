from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools import install_map_training_seed
from tools import training_data_store


class MapTrainingSeedTests(unittest.TestCase):
    def test_install_seed_merges_feedback_and_preserves_newer_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seed_dir = root / "seed"
            training_dir = root / "training"
            seed_dir.mkdir()
            training_dir.mkdir()

            seed_feedback = {
                "row": {
                    "candidate_id": "seed-1",
                    "place": "Seed Place",
                    "your_score": "pass",
                }
            }
            existing_feedback = {
                "row": {
                    "candidate_id": "live-1",
                    "place": "Live Place",
                    "your_score": "fail",
                }
            }
            (seed_dir / training_data_store.MAP_PLACE_REVIEW_FEEDBACK_ALL).write_text(
                json.dumps(seed_feedback) + "\n",
                encoding="utf-8",
            )
            destination_feedback = (
                training_dir / training_data_store.MAP_PLACE_REVIEW_FEEDBACK_ALL
            )
            destination_feedback.write_text(
                json.dumps(existing_feedback) + "\n",
                encoding="utf-8",
            )

            model_name = install_map_training_seed.MODEL_FILES[0]
            (seed_dir / model_name).write_text(
                json.dumps({"created_at": "2026-07-28T10:00:00+00:00", "source": "seed"}),
                encoding="utf-8",
            )
            (training_dir / model_name).write_text(
                json.dumps({"created_at": "2026-07-29T10:00:00+00:00", "source": "live"}),
                encoding="utf-8",
            )

            result = install_map_training_seed.install_seed(seed_dir, training_dir)

            rows = training_data_store.read_map_place_review_feedback_rows(
                [destination_feedback]
            )
            self.assertEqual({row["place"] for row in rows}, {"Seed Place", "Live Place"})
            model = json.loads((training_dir / model_name).read_text(encoding="utf-8"))
            self.assertEqual(model["source"], "live")
            self.assertEqual(result["feedback_rows_added"], 1)

    def test_install_seed_copies_newer_model_and_immutable_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seed_dir = root / "seed"
            training_dir = root / "training"
            seed_dir.mkdir()
            training_dir.mkdir()

            model_name = install_map_training_seed.MODEL_FILES[0]
            (seed_dir / model_name).write_text(
                json.dumps({"created_at": "2026-07-29T10:00:00+00:00", "source": "seed"}),
                encoding="utf-8",
            )
            (training_dir / model_name).write_text(
                json.dumps({"created_at": "2026-07-28T10:00:00+00:00", "source": "live"}),
                encoding="utf-8",
            )
            source_name = install_map_training_seed.IMMUTABLE_SOURCE_FILES[0]
            (seed_dir / source_name).write_text('{"example": true}\n', encoding="utf-8")

            result = install_map_training_seed.install_seed(seed_dir, training_dir)

            model = json.loads((training_dir / model_name).read_text(encoding="utf-8"))
            self.assertEqual(model["source"], "seed")
            self.assertTrue((training_dir / source_name).exists())
            self.assertIn(model_name, result["copied"])
            self.assertIn(source_name, result["copied"])


if __name__ == "__main__":
    unittest.main()

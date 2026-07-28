from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools import map_selector_model, training_data_store


class TrainingDataStoreTests(unittest.TestCase):
    def test_consolidates_map_place_review_feedback_with_dedupe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            training_dir = Path(tmpdir)
            first = training_dir / "map_place_review_feedback_20260720T100000Z.json"
            second = training_dir / "map_place_review_feedback_20260720T110000Z.json"
            row = {
                "place": "Good Stadium",
                "your_score": 10,
                "type": "stadium",
                "difficulty": "medium",
                "categories": "sport",
                "clues": {
                    "hard": "This stadium hosted a famous final.",
                    "medium": "It is located in a major city.",
                    "easy": "Look for the stadium beside the river.",
                },
            }
            first.write_text(json.dumps({"rows": [row]}), encoding="utf-8")
            second.write_text(json.dumps({"rows": [row, {**row, "place": "Good Bridge"}]}), encoding="utf-8")

            output = training_data_store.write_consolidated_map_place_review_feedback(training_dir)
            third = training_dir / "map_place_review_feedback_20260720T120000Z.json"
            third.write_text(
                json.dumps({"rows": [{**row, "place": "Good Castle"}]}),
                encoding="utf-8",
            )
            training_data_store.write_consolidated_map_place_review_feedback(training_dir)
            default_files = training_data_store.default_map_place_review_feedback_files(training_dir)
            rows = training_data_store.read_map_place_review_feedback_rows(default_files)

        self.assertEqual(output.name, training_data_store.MAP_PLACE_REVIEW_FEEDBACK_ALL)
        self.assertEqual([path.name for path in default_files], [training_data_store.MAP_PLACE_REVIEW_FEEDBACK_ALL])
        self.assertEqual(
            [row["place"] for row in rows],
            ["Good Stadium", "Good Bridge", "Good Castle"],
        )

    def test_selector_model_reads_consolidated_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            training_dir = Path(tmpdir)
            output = training_data_store.consolidated_map_place_review_feedback_file(training_dir)
            output.write_text(
                json.dumps(
                    {
                        "source_file": "review.json",
                        "source_index": 0,
                        "row": {
                            "place": "Good Stadium",
                            "your_score": 10,
                            "machine_score": 120,
                            "type": "stadium",
                            "difficulty": "medium",
                            "categories": "sport",
                            "clues": {
                                "hard": "This stadium hosted a famous final.",
                                "medium": "It is located in a major city.",
                                "easy": "Look for the stadium beside the river.",
                            },
                            "facts": [
                                "This stadium hosted a famous final.",
                                "It is located in a major city.",
                                "Look for the stadium beside the river.",
                            ],
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            model = map_selector_model.build_model_from_training_dir(training_dir)

        self.assertEqual(model["row_count"], 1)
        self.assertGreaterEqual(model["feature_count"], 1)


if __name__ == "__main__":
    unittest.main()

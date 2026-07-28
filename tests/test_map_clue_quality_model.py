from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import map_clue_quality_model


class MapClueQualityModelTests(unittest.TestCase):
    def sample_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for index in range(12):
            rows.extend(
                [
                    {
                        "row_id": f"hard-pass-{index}",
                        "level": "hard",
                        "label": "pass",
                        "clue": "A dramatic cup final here ended with a famous last-minute winning goal.",
                        "place_type": "stadium",
                        "weight": 1.0,
                        "source": "test",
                    },
                    {
                        "row_id": f"hard-fail-{index}",
                        "level": "hard",
                        "label": "fail",
                        "clue": "This historic building is famous and has impressive architecture.",
                        "place_type": "building",
                        "weight": 1.0,
                        "source": "test",
                    },
                ]
            )
        return rows

    def test_model_learns_pass_and_fail_language(self) -> None:
        model = map_clue_quality_model.fit_model(self.sample_rows())
        strong = map_clue_quality_model.predict_level(
            model,
            "hard",
            "A dramatic final here ended with a famous winning goal.",
            place_type="stadium",
        )
        weak = map_clue_quality_model.predict_level(
            model,
            "hard",
            "This historic building is famous for impressive architecture.",
            place_type="building",
        )
        self.assertGreater(strong["pass_probability"], weak["pass_probability"])

    def test_saved_model_round_trips(self) -> None:
        model = map_clue_quality_model.fit_model(self.sample_rows())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            map_clue_quality_model.save_model(model, path)
            loaded = map_clue_quality_model.load_model(path)
        self.assertEqual(loaded["version"], map_clue_quality_model.MODEL_VERSION)
        self.assertEqual(loaded["row_count"], len(self.sample_rows()))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools import map_selector_model


def review_row(
    *,
    place: str,
    score: int,
    place_type: str,
    categories: str,
    hard: str,
    medium: str,
    easy: str,
) -> dict[str, object]:
    return {
        "place": place,
        "your_score": score,
        "machine_score": 120,
        "type": place_type,
        "difficulty": "medium",
        "categories": categories,
        "clues": {
            "hard": hard,
            "medium": medium,
            "easy": easy,
            "reveal": place,
        },
        "facts": [hard, medium, easy],
        "map_guessability": easy,
    }


class MapSelectorModelTests(unittest.TestCase):
    def test_pass_fail_values_are_valid_training_scores(self) -> None:
        self.assertEqual(map_selector_model.numeric_score("pass"), 10)
        self.assertEqual(map_selector_model.numeric_score("fail"), 0)

    def test_architect_fact_does_not_score_as_a_hard_event_hook(self) -> None:
        architect = map_selector_model.hard_hook_score(
            "Architect Bernardo Morando designed this ideal Renaissance city."
        )
        incident = map_selector_model.hard_hook_score(
            "Uruguay beat Brazil 2-1 in the decisive 1950 World Cup match."
        )

        self.assertGreater(incident, architect)

    def test_fit_model_learns_basic_type_and_category_signal(self) -> None:
        rows = [
            review_row(
                place="Good Stadium",
                score=10,
                place_type="stadium",
                categories="sport; visual_landmark",
                hard="This stadium hosted a famous cup final.",
                medium="It is located in a major northern city.",
                easy="Look for the stadium beside the river and central park.",
            ),
            review_row(
                place="Good Bridge",
                score=8,
                place_type="bridge",
                categories="engineering_industry; visual_landmark",
                hard="This bridge survived a major earthquake during construction.",
                medium="It connects a city to a nearby island.",
                easy="Look for the long bridge crossing the strait.",
            ),
            review_row(
                place="Weak Tower",
                score=0,
                place_type="skyscraper",
                categories="visual_landmark",
                hard="Once the tallest building in the world, it defines the city skyline.",
                medium="It is in a large city.",
                easy="Look near the city centre.",
            ),
            review_row(
                place="Weak Palace",
                score=2,
                place_type="palace",
                categories="history",
                hard="This historic place is known for its past.",
                medium="It is in a country.",
                easy="Look somewhere near the old town.",
            ),
        ]

        model = map_selector_model.fit_model(rows, ridge=0.8)
        good = map_selector_model.predict_score(
            model,
            review_row(
                place="Candidate Stadium",
                score=0,
                place_type="stadium",
                categories="sport; visual_landmark",
                hard="This stadium hosted a famous final.",
                medium="It is located in a coastal city.",
                easy="Look for the stadium beside the waterfront park.",
            ),
        )
        weak = map_selector_model.predict_score(
            model,
            review_row(
                place="Candidate Tower",
                score=0,
                place_type="skyscraper",
                categories="visual_landmark",
                hard="Once the tallest free-standing structure in the world, it defines the city skyline.",
                medium="It is in a city.",
                easy="Look near the centre.",
            ),
        )

        self.assertGreater(model["row_count"], 0)
        self.assertGreater(good["ml_score"], weak["ml_score"])
        self.assertGreater(good["ml_rank_score"], weak["ml_rank_score"])

    def test_build_model_from_training_dir_reads_saved_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "map_place_review_feedback_20260720T100000Z.json"
            path.write_text(
                json.dumps(
                    {
                        "rows": [
                            review_row(
                                place="Good Stadium",
                                score=10,
                                place_type="stadium",
                                categories="sport",
                                hard="This stadium hosted a famous final.",
                                medium="It is located in a major city.",
                                easy="Look for the stadium beside the river.",
                            )
                        ]
                    }
                ),
                encoding="utf-8",
            )

            model = map_selector_model.build_model_from_training_dir(Path(tmpdir))

        self.assertEqual(model["row_count"], 1)
        self.assertGreaterEqual(model["feature_count"], 1)


if __name__ == "__main__":
    unittest.main()

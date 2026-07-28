from __future__ import annotations

import csv
import importlib
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

exporter = importlib.import_module("tools.export_map_clue_review_training_data")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class MapClueReviewTrainingExportTests(unittest.TestCase):
    def write_csv(self, path: Path, rows: list[dict[str, str]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=exporter.REQUIRED_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    def row(
        self,
        example_id: str,
        place_name: str,
        clue_level: str,
        label: str,
        *,
        categories: str = "",
        rewrite_needed: str = "no",
        rewritten_clue: str = "",
        weight: str = "1",
        exclude: str = "no",
        exclude_reason: str = "",
    ) -> dict[str, str]:
        return {
            "example_id": example_id,
            "place_name": place_name,
            "place_type": "landmark",
            "country": "United Kingdom",
            "admin1": "England",
            "lat": "53.463",
            "lng": "-2.291",
            "clue_level": clue_level,
            "original_clue": f"{place_name} test clue for {clue_level}",
            "label": label,
            "failure_categories": categories,
            "pass_reason": "Useful and playable." if label == "pass" else "",
            "fail_reason": "Fails the intended clue level." if label == "fail" else "",
            "rewrite_needed": rewrite_needed,
            "rewritten_clue": rewritten_clue,
            "training_weight": weight,
            "exclude_from_training": exclude,
            "exclude_reason": exclude_reason,
        }

    def test_exports_balanced_critic_rewrites_and_negative_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            csv_path = root / "reviews.csv"
            out_dir = root / "training"
            self.write_csv(
                csv_path,
                [
                    self.row("h-pass-1", "Old Trafford", "hard", "pass", weight="1"),
                    self.row("h-pass-2", "Tower Bridge", "hard", "pass", weight="2"),
                    self.row(
                        "h-fail-1",
                        "Stonehenge",
                        "hard",
                        "fail",
                        categories="weak_hard_hook",
                        rewrite_needed="yes",
                        rewritten_clue="A prehistoric stone ring draws solstice crowds.",
                    ),
                    self.row("m-pass-1", "Skellig Michael", "medium", "pass"),
                    self.row(
                        "m-fail-1",
                        "Luxor Temple",
                        "medium",
                        "fail",
                        categories="weak_medium_narrowing",
                        rewrite_needed="yes",
                        rewritten_clue="Look along the Nile for an ancient temple city.",
                    ),
                    self.row("e-pass-1", "Clifton Suspension Bridge", "easy", "pass"),
                    self.row(
                        "e-fail-1",
                        "Mount Rushmore",
                        "easy",
                        "fail",
                        categories="weak_easy_map_anchor",
                    ),
                    self.row(
                        "excluded",
                        "Rejected Place",
                        "easy",
                        "fail",
                        categories="factual_risk",
                        weight="0",
                        exclude="yes",
                        exclude_reason="Unverified source.",
                    ),
                ],
            )

            result = exporter.export_map_clue_review_training_data(
                csv_path,
                out_dir,
                eval_fraction=0,
                prefix="unit_review",
            )

            critic_rows = read_jsonl(result.critic_train_path)
            negative_rows = read_jsonl(result.negative_path)
            rewrite_rows = read_jsonl(result.rewrite_train_path)
            report = json.loads(result.report_path.read_text(encoding="utf-8"))

        critic_counts = Counter(
            (row["metadata"]["clue_level"], row["metadata"]["label"]) for row in critic_rows
        )
        self.assertEqual(len(critic_rows), 6)
        self.assertEqual(critic_counts[("hard", "pass")], 1)
        self.assertEqual(critic_counts[("hard", "fail")], 1)
        self.assertEqual(critic_counts[("medium", "pass")], 1)
        self.assertEqual(critic_counts[("medium", "fail")], 1)
        self.assertEqual(critic_counts[("easy", "pass")], 1)
        self.assertEqual(critic_counts[("easy", "fail")], 1)
        self.assertEqual(len(rewrite_rows), 2)
        self.assertEqual(len(negative_rows), 3)
        self.assertTrue(all(row["metadata"]["place"] != "Rejected Place" for row in negative_rows))
        self.assertEqual(
            negative_rows[0]["metadata"]["difficulty"],
            negative_rows[0]["metadata"]["clue_level"],
        )
        self.assertIn("failure_categories_included_fail", report)

    def test_validation_rejects_bad_training_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            csv_path = root / "bad.csv"
            self.write_csv(
                csv_path,
                [
                    self.row(
                        "bad-1",
                        "Bad Place",
                        "hard",
                        "fail",
                        categories="unknown_category",
                        weight="0",
                        rewrite_needed="yes",
                    )
                ],
            )

            with self.assertRaisesRegex(ValueError, "unknown_category"):
                exporter.export_map_clue_review_training_data(csv_path, root / "out")


if __name__ == "__main__":
    unittest.main()

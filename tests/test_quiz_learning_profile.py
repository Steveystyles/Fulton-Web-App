from __future__ import annotations

import importlib
import json
import unittest
from pathlib import Path

builder = importlib.import_module("tools.build_quiz_learning_profile")


class QuizLearningProfileTests(unittest.TestCase):
    def test_build_profile_summarizes_negative_patterns(self) -> None:
        records = [
            {
                "feedback_to_generator": (
                    "Question is under-specified: The player scored more than once, "
                    "so the question needs more detail. Possible valid answers: 17; 51."
                ),
                "metadata": {"reason": "review_failure"},
            },
            {
                "feedback_to_generator": (
                    "Low-quality confirmed football question scored 3/10. Answerable, "
                    "but date-based opponent recall is arbitrary; the easy rating is poorly calibrated."
                ),
                "metadata": {"reason": "low_review_score"},
            },
        ]

        profile = builder.build_profile(records, source=Path("negative.jsonl"))

        feedback = profile["feedback_by_slot"]["football/*"]
        self.assertEqual(profile["negative_count"], 2)
        self.assertEqual(profile["pattern_counts"]["underspecified_multi_answer"], 1)
        self.assertEqual(profile["pattern_counts"]["arbitrary_dated_fixture"], 1)
        self.assertTrue(any("under-specified" in item for item in feedback))
        self.assertTrue(any("arbitrary dated fixture" in item for item in feedback))
        self.assertEqual(profile["negative_reason_counts"]["review_failure"], 1)
        self.assertEqual(profile["negative_reason_counts"]["low_review_score"], 1)

    def test_build_profile_adds_slot_specific_guidance_from_failed_attempts(self) -> None:
        records = [
            {
                "feedback_to_generator": (
                    "The question relies on very recent information and the difficulty "
                    "is too low for a hard classification."
                ),
                "metadata": {
                    "reason": "daily_quiz_attempt_failure",
                    "subject": "football",
                    "difficulty": "hard",
                },
            },
            {
                "feedback_to_generator": (
                    "The claim is factually ambiguous and technically disputed because "
                    "the appearances are not officially recognized."
                ),
                "metadata": {
                    "reason": "daily_quiz_attempt_failure",
                    "subject": "football",
                    "difficulty": "hard",
                },
            },
        ]

        profile = builder.build_profile(records, source=Path("attempts.jsonl"))

        hard_feedback = profile["feedback_by_slot"]["football/hard"]
        self.assertTrue(any("recent-news recall" in item for item in hard_feedback))
        self.assertTrue(any("disputed classifications" in item for item in hard_feedback))
        self.assertEqual(
            profile["slot_pattern_counts"]["football/hard"]["recent_news_not_durable"],
            1,
        )


if __name__ == "__main__":
    unittest.main()

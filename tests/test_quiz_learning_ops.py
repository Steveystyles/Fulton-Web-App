from __future__ import annotations

import importlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import daily_quiz

impact = importlib.import_module("tools.report_quiz_learning_impact")
refresh = importlib.import_module("tools.refresh_quiz_learning_profile")


def ops_question(*, subject: str = "football", difficulty: str = "easy") -> dict[str, object]:
    return {
        "subject": subject,
        "difficulty": difficulty,
        "question": "Which club won this verified quiz-learning fixture?",
        "choices": ["Arsenal", "Chelsea", "Leeds United", "Everton"],
        "correct_answer": "Arsenal",
        "explanation": "Arsenal is the verified answer for this fixture.",
        "interesting_reason": "The question checks whether operational reports count accepted quiz items.",
        "tags": ["ops-learning", "fixture"],
    }


class QuizLearningOpsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        daily_quiz.initialize_database(self.conn)
        self.addCleanup(self.conn.close)

    def add_published_question(self, *, date: str) -> None:
        quiz_set = daily_quiz.get_or_create_quiz_set(self.conn, date)
        daily_quiz.save_question(
            self.conn,
            quiz_set_id=int(quiz_set["id"]),
            question=ops_question(),
        )
        daily_quiz.set_quiz_status(self.conn, date, "published")

    def add_attempt(
        self,
        *,
        date: str,
        passed: bool,
        failure_reason: str | None,
        critic: dict[str, object] | None = None,
    ) -> None:
        daily_quiz.save_attempt(
            self.conn,
            quiz_date=date,
            subject="football",
            difficulty="easy",
            attempt_number=1,
            provider="test-provider",
            generated={"question": "Generated candidate"},
            critic=critic,
            passed=passed,
            failure_reason=failure_reason,
        )

    def test_learning_impact_report_compares_activation_phases(self) -> None:
        self.add_published_question(date="2026-07-13")
        self.add_attempt(date="2026-07-13", passed=False, failure_reason="HTTP 429 from provider")
        self.add_attempt(date="2026-07-13", passed=True, failure_reason=None)

        self.add_published_question(date="2026-07-14")
        self.add_attempt(
            date="2026-07-14",
            passed=False,
            failure_reason="Correct answer already appeared recently in this quiz slot.",
        )
        self.add_attempt(
            date="2026-07-14",
            passed=False,
            failure_reason="Critic scores did not meet publication thresholds.",
            critic={
                "passed": False,
                "scores": {
                    "validity": 10,
                    "correctness": 8,
                    "difficulty_match": 8,
                    "interestingness": 4,
                    "non_repetition": 8,
                },
                "failure_reasons": ["Too generic."],
            },
        )
        self.add_attempt(date="2026-07-14", passed=True, failure_reason=None)

        report = impact.build_learning_impact_report(
            self.conn,
            activation_date="2026-07-14",
        )

        self.assertEqual(report["by_phase"]["before"]["attempts"], 2)
        self.assertEqual(report["by_phase"]["before"]["failure_categories"]["provider_transient"], 1)
        self.assertEqual(report["by_phase"]["after"]["attempts"], 3)
        self.assertEqual(report["by_phase"]["after"]["accepted_questions"], 1)
        self.assertEqual(report["by_phase"]["after"]["failure_categories"]["repetition"], 1)
        self.assertEqual(report["by_phase"]["after"]["failure_categories"]["critic"], 1)

    def test_refresh_profile_combines_review_file_and_failed_attempts(self) -> None:
        self.add_attempt(
            date="2026-07-14",
            passed=False,
            failure_reason="Question is too similar to a recent accepted question.",
            critic={
                "passed": False,
                "failure_reasons": ["Too generic."],
                "feedback_to_generator": "Avoid repeating recent football answers.",
                "scores": {
                    "validity": 9,
                    "correctness": 9,
                    "difficulty_match": 8,
                    "interestingness": 5,
                    "non_repetition": 4,
                },
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            negative_path = Path(tmpdir) / "football_review_negative_test.jsonl"
            negative_path.write_text(
                json.dumps(
                    {
                        "feedback_to_generator": "Question is under-specified and has possible valid answers.",
                        "metadata": {"reason": "review_failure"},
                    },
                    ensure_ascii=True,
                )
                + "\n",
                encoding="utf-8",
            )

            profile = refresh.build_candidate_profile(
                self.conn,
                negative_files=[negative_path],
                since_date="2026-07-14",
            )

        self.assertTrue(profile["validation"]["passed"])
        self.assertEqual(profile["failed_attempt_record_count"], 3)
        self.assertEqual(profile["pattern_counts"]["underspecified_multi_answer"], 1)
        self.assertIn("football/*", profile["feedback_by_slot"])

    def test_validate_profile_rejects_duplicates_and_long_feedback(self) -> None:
        errors = refresh.validate_profile(
            {
                "feedback_by_slot": {
                    "football/*": [
                        "Avoid repeats.",
                        "Avoid repeats.",
                        "x" * 241,
                    ]
                }
            }
        )

        self.assertTrue(any("duplicate" in error for error in errors))
        self.assertTrue(any("longer than 240" in error for error in errors))

    def test_refresh_profile_adds_smoothed_candidate_policy(self) -> None:
        quiz_set = daily_quiz.get_or_create_quiz_set(self.conn, "2026-07-15")
        candidate = {
            "answer": "Example FC",
            "hook": "A documented final made this club a useful candidate for the learning fixture.",
            "topic_lane": "famous incidents and matches",
            "era": "twentieth century",
            "region": "Europe",
            "tags": ["famous final", "learning fixture"],
            "evidence_query": "Example FC documented final",
        }
        daily_quiz.insert_candidate(
            self.conn,
            quiz_set_id=int(quiz_set["id"]),
            quiz_date="2026-07-15",
            subject="football",
            difficulty="easy",
            batch_number=1,
            candidate_index=1,
            provider="test-provider",
            generation_mode="normal",
            candidate=candidate,
            status="accepted",
        )
        rejected = {**candidate, "answer": "Rejected FC", "evidence_query": "Rejected FC final"}
        daily_quiz.insert_candidate(
            self.conn,
            quiz_set_id=int(quiz_set["id"]),
            quiz_date="2026-07-15",
            subject="football",
            difficulty="easy",
            batch_number=1,
            candidate_index=2,
            provider="test-provider",
            generation_mode="normal",
            candidate=rejected,
            status="rejected",
            rejection_stage="evidence",
            failure_reason="Evidence did not support the hook.",
        )

        policy = refresh.candidate_policy_from_database(self.conn)

        slot = policy["football/easy"]
        self.assertEqual(slot["sample_count"], 2)
        self.assertEqual(slot["lane_weights"]["famous incidents and matches"], 0.5)
        self.assertEqual(slot["provider_weights"]["test-provider"], 0.5)
        self.assertEqual(slot["failure_categories"]["evidence"], 1)


if __name__ == "__main__":
    unittest.main()

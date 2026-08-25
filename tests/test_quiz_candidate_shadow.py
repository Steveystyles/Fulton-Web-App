from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import daily_quiz
from tools import evaluate_quiz_candidate_pipeline as shadow


def shadow_question(
    subject: str,
    difficulty: str,
    *,
    answer: str,
    suffix: str,
) -> dict[str, object]:
    return {
        "subject": subject,
        "difficulty": difficulty,
        "question": f"Which documented answer matches the shadow fixture for {suffix}?",
        "choices": [answer, f"Wrong A {suffix}", f"Wrong B {suffix}", f"Wrong C {suffix}"],
        "correct_answer": answer,
        "explanation": f"The evidence for {suffix} identifies {answer} as the documented answer.",
        "interesting_reason": f"This shadow fixture records a stable and sourceable fact about {answer}.",
        "tags": [f"shadow-{suffix}", f"topic-{difficulty}"],
    }


class QuizCandidateShadowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        daily_quiz.initialize_database(self.conn)
        self.addCleanup(self.conn.close)

    def add_quiz(self, quiz_date: str, *, repeated_answer: str | None = None) -> None:
        quiz_set = daily_quiz.get_or_create_quiz_set(self.conn, quiz_date)
        for subject in daily_quiz.SUBJECTS:
            for difficulty in daily_quiz.DIFFICULTIES:
                suffix = f"{quiz_date}-{subject}-{difficulty}"
                answer = repeated_answer or f"Answer {suffix}"
                daily_quiz.save_question(
                    self.conn,
                    quiz_set_id=int(quiz_set["id"]),
                    question=shadow_question(
                        subject, difficulty, answer=answer, suffix=suffix
                    ),
                    evidence=[],
                    verification={"passed": True},
                )
        self.conn.execute(
            """
            UPDATE daily_quiz_sets SET pipeline_version='candidate-v1'
            WHERE id=?
            """,
            (quiz_set["id"],),
        )
        daily_quiz.set_quiz_status(self.conn, quiz_date, "published")

    def test_shadow_audit_detects_answer_collision(self) -> None:
        self.add_quiz("2026-08-20", repeated_answer="Repeated Answer")
        self.add_quiz("2026-08-21", repeated_answer="Repeated Answer")

        collisions = shadow.answer_collisions(self.conn, "2026-08-21", 45)

        self.assertEqual(collisions, 2)

    def test_review_export_contains_two_questions_per_slot(self) -> None:
        self.add_quiz("2026-08-20")
        self.add_quiz("2026-08-21")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "review.csv"
            shadow.write_review_sample(self.conn, path)
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 12)
        self.assertEqual(
            {(row["subject"], row["difficulty"]) for row in rows},
            {
                (subject, difficulty)
                for subject in daily_quiz.SUBJECTS
                for difficulty in daily_quiz.DIFFICULTIES
            },
        )

    def test_shadow_reset_removes_copied_target_without_erasing_history(self) -> None:
        self.add_quiz("2026-08-19")
        self.add_quiz("2026-08-20")
        target = self.conn.execute(
            "SELECT id FROM daily_quiz_sets WHERE quiz_date='2026-08-20'"
        ).fetchone()
        self.conn.execute(
            "UPDATE daily_quiz_sets SET pipeline_version='legacy' WHERE id=?",
            (target["id"],),
        )
        self.conn.execute(
            """
            INSERT INTO daily_quiz_attempts (
                quiz_date, subject, difficulty, attempt_number, provider,
                generated_json, passed, created_at
            ) VALUES ('2026-08-20', 'football', 'easy', 1, 'legacy', '{}', 0, 'now')
            """
        )
        daily_quiz.insert_candidate(
            self.conn,
            quiz_set_id=int(target["id"]),
            quiz_date="2026-08-20",
            subject="football",
            difficulty="easy",
            batch_number=1,
            candidate_index=1,
            provider="legacy",
            generation_mode="normal",
            candidate={
                "answer": "Copied Answer",
                "hook": "A copied candidate that must not enter the shadow run.",
                "topic_lane": "famous incidents and matches",
                "era": "",
                "region": "",
                "tags": ["copied"],
                "evidence_query": "Copied Answer candidate",
            },
            status="eligible",
        )

        shadow.reset_shadow_target_dates(self.conn, ["2026-08-20"])

        self.assertIsNotNone(
            self.conn.execute(
                "SELECT 1 FROM daily_quiz_sets WHERE quiz_date='2026-08-19'"
            ).fetchone()
        )
        self.assertIsNone(
            self.conn.execute(
                "SELECT 1 FROM daily_quiz_sets WHERE quiz_date='2026-08-20'"
            ).fetchone()
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM daily_quiz_attempts WHERE quiz_date='2026-08-20'"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM daily_quiz_candidates WHERE quiz_date='2026-08-20'"
            ).fetchone()[0],
            0,
        )

    def test_provider_capacity_detection_requires_chain_quota_failure(self) -> None:
        self.assertTrue(
            shadow.provider_capacity_exhausted(
                [
                    "Candidate discovery failed: All AI providers failed: "
                    "Gemini RESOURCE_EXHAUSTED free_tier_requests; "
                    "OpenRouter free-models-per-day"
                ]
            )
        )
        self.assertFalse(
            shadow.provider_capacity_exhausted(
                ["One candidate was rejected because its evidence was incomplete."]
            )
        )

    def test_shadow_run_pauses_before_later_dates_when_provider_quota_is_exhausted(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_db = root / "source.db"
            source_conn = sqlite3.connect(source_db)
            source_conn.row_factory = sqlite3.Row
            daily_quiz.initialize_database(source_conn)
            source_conn.close()
            calls: list[str] = []

            def quota_failure(
                conn: sqlite3.Connection,
                *,
                quiz_date: str,
                log: object,
                **_: object,
            ) -> dict[str, object]:
                calls.append(quiz_date)
                quiz_set = daily_quiz.get_or_create_quiz_set(conn, quiz_date)
                conn.execute(
                    "UPDATE daily_quiz_sets SET pipeline_version='candidate-v1' WHERE id=?",
                    (quiz_set["id"],),
                )
                conn.commit()
                log(
                    "Candidate discovery failed: All AI providers failed: "
                    "RESOURCE_EXHAUSTED free_tier_requests; free-models-per-day"
                )
                return daily_quiz.quiz_status(conn, quiz_date)

            args = SimpleNamespace(
                db=source_db,
                output_dir=root / "output",
                start_date="2026-08-20",
                days=2,
                max_rounds=16,
                retry_delay_seconds=0,
                resume=False,
            )
            config_stub = SimpleNamespace(
                answer_embargo_days=45,
                question_similarity_days=180,
                candidate_max_calls_per_quiz=30,
            )
            with (
                patch.object(shadow.daily_quiz.QuizConfig, "from_env", return_value=object()),
                patch.object(shadow, "replace", return_value=config_stub),
                patch.object(
                    shadow.daily_quiz,
                    "generate_daily_quiz",
                    side_effect=quota_failure,
                ),
            ):
                report = shadow.evaluate(args)

        self.assertEqual(calls, ["2026-08-20"])
        self.assertEqual(report["run_status"], "paused_provider_quota")
        self.assertTrue(report["resumable"])
        self.assertEqual(report["results"][1]["status"], "pending")

    def test_shadow_run_stops_before_provider_call_when_budget_is_already_spent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "output"
            output_dir.mkdir()
            source_db = output_dir / "shadow.db"
            source_conn = sqlite3.connect(source_db)
            source_conn.row_factory = sqlite3.Row
            daily_quiz.initialize_database(source_conn)
            quiz_set = daily_quiz.get_or_create_quiz_set(source_conn, "2026-08-20")
            source_conn.execute(
                "UPDATE daily_quiz_sets SET pipeline_version='candidate-v1' WHERE id=?",
                (quiz_set["id"],),
            )
            for batch_number in range(1, 31):
                daily_quiz.insert_candidate(
                    source_conn,
                    quiz_set_id=int(quiz_set["id"]),
                    quiz_date="2026-08-20",
                    subject="football",
                    difficulty="easy",
                    batch_number=batch_number,
                    candidate_index=1,
                    provider="test",
                    generation_mode="normal",
                    candidate={
                        "answer": f"Answer {batch_number}",
                        "hook": f"Documented candidate hook {batch_number} for the budget test.",
                        "topic_lane": "famous incidents and matches",
                        "era": "",
                        "region": "",
                        "tags": ["test", f"batch-{batch_number}"],
                        "evidence_query": f"Answer {batch_number} documented event",
                    },
                    status="rejected",
                    rejection_stage="local",
                    failure_reason="Rejected fixture.",
                )
            source_conn.close()
            args = SimpleNamespace(
                db=source_db,
                output_dir=output_dir,
                start_date="2026-08-20",
                days=1,
                max_rounds=2,
                retry_delay_seconds=0,
                resume=True,
            )
            config_stub = SimpleNamespace(
                answer_embargo_days=45,
                question_similarity_days=180,
                candidate_max_calls_per_quiz=30,
            )
            with (
                patch.object(shadow.daily_quiz.QuizConfig, "from_env", return_value=object()),
                patch.object(shadow, "replace", return_value=config_stub),
                patch.object(shadow.daily_quiz, "generate_daily_quiz") as generate,
            ):
                report = shadow.evaluate(args)

        generate.assert_not_called()
        self.assertEqual(report["run_status"], "failed_call_budget")
        self.assertEqual(report["results"][0]["generation_calls"], 30)


if __name__ == "__main__":
    unittest.main()

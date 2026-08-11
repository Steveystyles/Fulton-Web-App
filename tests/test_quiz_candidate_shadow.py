from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()

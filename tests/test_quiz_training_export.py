from __future__ import annotations

import importlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import daily_quiz

exporter = importlib.import_module("tools.export_quiz_training_data")


def export_question(
    *,
    date: str,
    subject: str = "football",
    difficulty: str = "easy",
    label: str,
) -> dict[str, object]:
    return {
        "subject": subject,
        "difficulty": difficulty,
        "question": f"Which archive clue identifies {label} for the training export example?",
        "choices": [
            f"{label} answer",
            f"{label} distractor one",
            f"{label} distractor two",
            f"{label} distractor three",
        ],
        "correct_answer": f"{label} answer",
        "explanation": f"The {label} answer is the only option matching the archived quiz clue.",
        "interesting_reason": f"The {label} clue checks a specific reusable quiz-writing pattern.",
        "tags": [label, "training-export"],
    }


class QuizTrainingExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        daily_quiz.initialize_database(self.conn)
        self.addCleanup(self.conn.close)

    def add_question(self, *, date: str, label: str, created_at: str) -> None:
        quiz_set = daily_quiz.get_or_create_quiz_set(self.conn, date)
        daily_quiz.save_question(
            self.conn,
            quiz_set_id=int(quiz_set["id"]),
            question=export_question(date=date, label=label),
        )
        self.conn.execute(
            """
            UPDATE daily_quiz_questions
            SET created_at = ?
            WHERE quiz_set_id = ?
            """,
            (created_at, quiz_set["id"]),
        )
        daily_quiz.set_quiz_status(self.conn, date, "published")

    def add_failed_attempt(self, *, date: str, created_at: str) -> None:
        daily_quiz.save_attempt(
            self.conn,
            quiz_date=date,
            subject="football",
            difficulty="easy",
            attempt_number=1,
            provider="test-provider",
            generated={"question": "Which bland football question should be rejected?"},
            critic={
                "feedback_to_generator": "Use a more specific and memorable football clue."
            },
            passed=False,
            failure_reason="Question is too generic.",
        )
        self.conn.execute(
            """
            UPDATE daily_quiz_attempts
            SET created_at = ?
            WHERE quiz_date = ? AND subject = 'football' AND difficulty = 'easy'
            """,
            (created_at, date),
        )

    def test_export_writes_training_and_eval_jsonl(self) -> None:
        self.add_question(
            date="2026-06-01",
            label="first",
            created_at="2026-06-01T00:00:00+00:00",
        )
        self.add_failed_attempt(
            date="2026-06-02",
            created_at="2026-06-02T00:01:00+00:00",
        )
        self.add_question(
            date="2026-06-02",
            label="second",
            created_at="2026-06-02T00:02:00+00:00",
        )
        self.add_question(
            date="2026-06-03",
            label="third",
            created_at="2026-06-03T00:00:00+00:00",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = exporter.export_training_data(
                self.conn,
                Path(tmpdir),
                eval_days=1,
                prefix="test_quiz",
            )
            train_records = [
                json.loads(line)
                for line in result.train_path.read_text(encoding="utf-8").splitlines()
            ]
            eval_records = [
                json.loads(line)
                for line in result.eval_path.read_text(encoding="utf-8").splitlines()
            ]
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(result.train_count, 2)
        self.assertEqual(result.eval_count, 1)
        self.assertEqual(result.eval_dates, ["2026-06-03"])
        self.assertEqual(manifest["train_count"], 2)
        self.assertEqual(manifest["eval_count"], 1)
        self.assertTrue(all(set(record) == {"messages"} for record in train_records))
        self.assertEqual(eval_records[0]["metadata"]["quiz_date"], "2026-06-03")

        second_record = next(
            record
            for record in train_records
            if "second answer" in record["messages"][2]["content"]
        )
        prompt = second_record["messages"][1]["content"]
        self.assertIn("Which archive clue identifies first", prompt)
        self.assertIn("Use a more specific and memorable football clue.", prompt)
        self.assertIn("Question is too generic.", prompt)

    def test_export_requires_published_questions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(ValueError, "No published daily quiz questions"):
                exporter.export_training_data(self.conn, Path(tmpdir))


if __name__ == "__main__":
    unittest.main()

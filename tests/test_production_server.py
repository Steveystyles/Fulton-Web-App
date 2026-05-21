from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


class ProductionServerHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def test_password_policy_requires_longer_passwords(self) -> None:
        import production_server

        self.assertIsNotNone(production_server.validate_password("short"))
        self.assertIsNone(production_server.validate_password("correct-horse-battery"))

    def test_session_cookie_can_be_marked_secure(self) -> None:
        import production_server

        header = production_server.session_header("token-value")
        self.assertIn("HttpOnly", header)
        self.assertIn("SameSite=Lax", header)
        self.assertIn("Secure", header)

    def test_production_database_does_not_seed_demo_users_by_default(self) -> None:
        import production_server
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        original_quiz_data_dir = server.QUIZ_DATA_DIR
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.QUIZ_DATA_DIR = data_dir / "quizzes"
            production_server.initialize_database()

            with closing(server.connect_db()) as conn:
                count = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
            self.assertEqual(count, 0)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path
            server.QUIZ_DATA_DIR = original_quiz_data_dir

    def test_daily_quiz_generation_does_not_use_report_placeholder_questions(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        original_quiz_data_dir = server.QUIZ_DATA_DIR
        original_api_key = server.QUIZ_OPENAI_API_KEY
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.QUIZ_DATA_DIR = data_dir / "quizzes"
            server.QUIZ_OPENAI_API_KEY = ""

            payload = server.ensure_daily_questions()
            question_texts = {
                question["question"]
                for category in ("football", "general")
                for question in payload[category]
            }

            self.assertFalse(
                server.LEGACY_PLACEHOLDER_QUESTION_TEXTS.intersection(question_texts)
            )
            self.assertTrue(server.validate_daily_questions(payload))
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path
            server.QUIZ_DATA_DIR = original_quiz_data_dir
            server.QUIZ_OPENAI_API_KEY = original_api_key


if __name__ == "__main__":
    unittest.main()

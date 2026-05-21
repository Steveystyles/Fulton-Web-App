from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


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

    def test_history_events_prefer_recent_sport_and_birth_highlights(self) -> None:
        import server

        source_payload = {
            "data": {
                "Events": [
                    {"year": "45 BC", "text": "A very old event happened.", "links": []},
                    {"year": "2021", "text": "A landmark science mission launched.", "links": []},
                    {"year": "1967", "text": "A football club won a European cup.", "links": []},
                    {"year": "1998", "text": "A major agreement was signed.", "links": []},
                ],
                "Births": [
                    {"year": "1987", "text": "A famous singer and actor was born.", "links": []},
                    {"year": "1880", "text": "A local clerk was born.", "links": []},
                ],
            }
        }

        with patch("server.fetch_json_url", return_value=source_payload):
            events = server.fetch_history_events(5, 21, 5)

        categories = {event.get("category") for event in events}
        event_text = " ".join(event["text"] for event in events)

        self.assertIn("history", categories)
        self.assertIn("sport", categories)
        self.assertIn("born", categories)
        self.assertIn("football club won", event_text)
        self.assertIn("famous singer and actor", event_text)
        self.assertNotEqual(events[0]["year"], "45 BC")


if __name__ == "__main__":
    unittest.main()

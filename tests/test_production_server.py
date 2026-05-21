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

    def test_production_permissions_policy_allows_geolocation(self) -> None:
        import production_server

        sent_headers: list[tuple[str, str]] = []

        class DummyHandler:
            def send_header(self, name: str, value: str) -> None:
                sent_headers.append((name, value))

        def original_end_headers(handler: DummyHandler) -> None:
            handler.send_header(
                "Permissions-Policy",
                "camera=(), microphone=(), geolocation=(self)",
            )

        with patch.object(production_server, "_original_end_headers", original_end_headers):
            production_server.end_headers(DummyHandler())  # type: ignore[arg-type]

        policy_headers = [
            value for name, value in sent_headers if name.lower() == "permissions-policy"
        ]
        self.assertEqual(policy_headers, ["camera=(), microphone=(), geolocation=(self)"])

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

    def test_wikipedia_summary_prefers_paisley_town_alias(self) -> None:
        import server

        with patch("server.fetch_json_url", return_value={"title": "Paisley, Renfrewshire"}) as fetch:
            payload = server.fetch_wikipedia_summary("Paisley", "en")

        self.assertEqual(payload["title"], "Paisley, Renfrewshire")
        self.assertIn("Paisley,_Renfrewshire", fetch.call_args[0][0])

    def test_location_facts_are_themed_sourced_and_structured(self) -> None:
        import server

        summary = {
            "title": "Paisley, Renfrewshire",
            "extract": (
                "Paisley is a town in Renfrewshire, Scotland. "
                "Paisley Abbey is a medieval landmark in the town."
            ),
        }
        extract = (
            "Paisley became known for its textile industry and the Paisley pattern. "
            "The town has hosted cultural events and arts activity. "
            "Notable people from Paisley include writers, musicians and footballers. "
            "The historic centre contains important public buildings and churches."
        )
        entity = {
            "id": "Q123",
            "labels": {"en": {"value": "Paisley"}},
            "claims": {
                "P31": [
                    {"mainsnak": {"datavalue": {"value": {"numeric-id": 486972}}}},
                ],
                "P1082": [
                    {"mainsnak": {"datavalue": {"value": {"amount": "+77220"}}}},
                ],
                "P571": [
                    {"mainsnak": {"datavalue": {"value": {"time": "+1157-01-01T00:00:00Z"}}}},
                ],
                "P131": [
                    {"mainsnak": {"datavalue": {"value": {"numeric-id": 211091}}}},
                ],
            },
        }

        with patch(
            "server.fetch_wikidata_labels",
            return_value={"Q486972": "human settlement", "Q211091": "Renfrewshire"},
        ):
            profile = server.wikidata_profile(entity, "en", "Paisley")
            facts = server.build_location_facts(
                summary,
                extract,
                8,
                "https://en.wikipedia.org/wiki/Paisley,_Renfrewshire",
            )

        self.assertEqual(profile["population"], "77,220")
        self.assertEqual(profile["areas"], ["Renfrewshire"])
        self.assertGreaterEqual(len(facts), 6)
        self.assertTrue(all(isinstance(fact, dict) for fact in facts))
        self.assertTrue(all(fact["sourceName"] and fact["sourceUrl"] for fact in facts))
        self.assertTrue(all(fact["confidence"] in {"high", "medium", "low"} for fact in facts))
        self.assertEqual({fact["sourceName"] for fact in facts}, {"Wikipedia"})
        self.assertTrue({"history", "landmark", "industry", "culture"}.intersection(
            {fact["theme"] for fact in facts}
        ))

    def test_quiz_order_and_scoring_use_difficulty_weights(self) -> None:
        import server

        questions = [
            {"difficulty": "hard", "correct_answer": "H"},
            {"difficulty": "easy", "correct_answer": "E"},
            {"difficulty": "medium", "correct_answer": "M"},
        ]
        payload = {"date": "2026-05-22", "football": questions, "general": questions}
        ordered = server.order_daily_questions(payload)

        self.assertEqual(
            [question["difficulty"] for question in ordered["football"]],
            ["easy", "medium", "hard"],
        )
        self.assertEqual(
            server.score_quiz_answers(ordered["football"], ["E", "wrong", "H"]),
            {"score": 6, "maxScore": 9, "correctCount": 2},
        )

    def test_wordle_points_curve(self) -> None:
        import server

        self.assertEqual([server.wordle_score("won", attempt) for attempt in range(1, 7)], [10, 5, 4, 3, 2, 1])
        self.assertEqual(server.wordle_score("lost", 6), 0)

    def test_leaderboard_excludes_admin_accounts(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        original_quiz_data_dir = server.QUIZ_DATA_DIR
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.QUIZ_DATA_DIR = data_dir / "quizzes"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-05-22T12:00:00+00:00"
                with conn:
                    conn.execute(
                        "INSERT INTO users (username, password_hash, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                        ("admin", "hash", "admin", now, now),
                    )
                    conn.execute(
                        "INSERT INTO users (username, password_hash, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                        ("dad", "hash", "user", now, now),
                    )
                    rows = conn.execute("SELECT id, username FROM users").fetchall()
                    user_ids = {row["username"]: row["id"] for row in rows}
                    for username, score in (("admin", 9), ("dad", 6)):
                        conn.execute(
                            """
                            INSERT INTO daily_quiz_results (
                                user_id, game_date, category, answers_json, score, max_score,
                                correct_count, completed_at, created_at, updated_at
                            )
                            VALUES (?, ?, 'football', '[]', ?, 9, 2, ?, ?, ?)
                            """,
                            (user_ids[username], "2026-05-22", score, now, now, now),
                        )
                payload = server.leaderboard_payload(conn)

            self.assertEqual([player["username"] for player in payload["players"]], ["dad"])
            self.assertEqual(payload["players"][0]["totalPoints"], 6)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path
            server.QUIZ_DATA_DIR = original_quiz_data_dir

    def test_moderator_flag_exposes_mod_role_and_player_management(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        original_quiz_data_dir = server.QUIZ_DATA_DIR
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.QUIZ_DATA_DIR = data_dir / "quizzes"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-05-22T12:00:00+00:00"
                with conn:
                    conn.execute(
                        """
                        INSERT INTO users (
                            username, password_hash, role, is_moderator, created_at, updated_at
                        )
                        VALUES ('dad', 'hash', 'user', 1, ?, ?)
                        """,
                        (now, now),
                    )
                dad = conn.execute("SELECT * FROM users WHERE username = 'dad'").fetchone()

            self.assertEqual(server.user_payload(dad)["role"], "mod")
            self.assertTrue(server.user_can_manage_players(dad))
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path
            server.QUIZ_DATA_DIR = original_quiz_data_dir

    def test_news_classifier_does_not_mark_routine_stories_as_breaking(self) -> None:
        import server

        routine_titles = [
            "8 emerging transfer headlines as Hibs and Aberdeen eye centre backs",
            "Craig McLeish on St Mirren injury news and contract talks",
            "Premier Sports Cup group stage draw date and time confirmed",
            "Lack of goals could be Buddies' downfall in play-off clash",
            "St Mirren warm-up for their relegation play-off",
        ]

        for title in routine_titles:
            with self.subTest(title=title):
                priority, tags = server.classify_news_item(title, "", ["breaking"])
                self.assertEqual(priority, "news")
                self.assertNotIn("breaking", tags)

    def test_news_classifier_keeps_explicit_breaking_and_live_scores(self) -> None:
        import server

        breaking_priority, breaking_tags = server.classify_news_item(
            "Breaking: St Mirren appoint new manager",
            "",
            [],
        )
        live_priority, live_tags = server.classify_news_item(
            "Partick Thistle v St Mirren live score and match centre",
            "",
            [],
        )

        self.assertEqual(breaking_priority, "breaking")
        self.assertIn("breaking", breaking_tags)
        self.assertEqual(live_priority, "live-scores")
        self.assertIn("live-scores", live_tags)

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

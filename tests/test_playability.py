"""Player-state and league regressions, using only disposable SQLite data."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import closing
from types import SimpleNamespace

import server
import playability
import daily_map_game


class PlayabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for name, value in (("DATA_DIR", Path(self.temp.name)), ("DB_PATH", Path(self.temp.name) / "test.db"), ("SEED_DEMO_USERS", False)):
            if hasattr(server, name):
                mocked = patch.object(server, name, value)
                mocked.start()
                self.addCleanup(mocked.stop)
        mocked = patch.object(server, "today_game_date", return_value="2026-09-09")
        mocked.start()
        self.addCleanup(mocked.stop)
        server.initialize_database()
        self.conn = server.connect_db()
        self.addCleanup(self.conn.close)
        now = server.utc_now()
        self.user = self.conn.execute("INSERT INTO users (username,password_hash,role,created_at,updated_at) VALUES ('player','hash','user',?,?)", (now, now)).lastrowid
        self.other = self.conn.execute("INSERT INTO users (username,password_hash,role,created_at,updated_at) VALUES ('other','hash','user',?,?)", (now, now)).lastrowid
        self.quiz_id = self.conn.execute("INSERT INTO daily_quiz_sets (quiz_date,status,published_at) VALUES ('2026-09-09','published',?)", (now,)).lastrowid
        for subject in ("football", "general_knowledge"):
            for difficulty in ("easy", "medium", "hard"):
                self.conn.execute(
                    "INSERT INTO daily_quiz_questions (quiz_set_id,subject,difficulty,question,choices_json,correct_answer,explanation,interesting_reason,tags_json,normalized_question,created_at) "
                    "VALUES (?,?,?,?,?,'A','An explanation.','Interesting.','[]',?,?)",
                    (self.quiz_id, subject, difficulty, f"{subject} {difficulty}?", json.dumps(["A", "B", "C", "D"]), f"{subject} {difficulty}", now),
                )
        self.conn.commit()
        self.questions = [q for q in server.daily_quiz.quiz_payload(self.conn, "2026-09-09")["questions"] if q["subject"] == "football"]
        self.answers = [{"questionId": q["id"], "choiceId": q["choices"][0]["id"]} for q in self.questions]

    def save(self, answers):
        with self.conn:
            return server.save_daily_quiz_progress(self.conn, self.user, "2026-09-09", "football", answers)

    def test_progress_survives_new_connection_and_is_private(self):
        payload, status = self.save(self.answers[:1])
        self.assertEqual(status, 200)
        self.assertNotIn("result", payload)
        with closing(server.connect_db()) as another_device:
            state = server.daily_quiz_player_state(another_device, self.user, "2026-09-09")
            self.assertEqual(state["progress"]["football"], self.answers[:1])
            self.assertEqual(state["results"], {})
            self.assertEqual(server.daily_quiz_player_state(another_device, self.other, "2026-09-09"), {"progress": {}, "results": {}})

    def test_confirmation_locks_answer_and_rejects_stale_device(self):
        self.save(self.answers[:1])
        changed = [{"questionId": self.questions[0]["id"], "choiceId": self.questions[0]["choices"][1]["id"]}]
        self.assertEqual(self.save(changed)[1], 409)
        self.save(self.answers[:2])
        self.assertEqual(self.save(self.answers[:1])[1], 409)

    def test_final_result_is_authoritative_and_idempotent(self):
        first, status = self.save(self.answers)
        self.assertEqual(status, 201)
        self.assertEqual(first["result"]["correctCount"], 3)
        changed = [{"questionId": q["id"], "choiceId": q["choices"][1]["id"]} for q in self.questions]
        replay, status = self.save(changed)
        self.assertEqual(status, 200)
        self.assertEqual(replay["result"], first["result"])
        self.assertEqual(server.daily_quiz_player_state(self.conn, self.user, "2026-09-09")["results"]["football"], first["result"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM daily_quiz_results").fetchone()[0], 1)

    def test_old_result_endpoint_cannot_overwrite_locked_answers(self):
        self.save(self.answers[:1])
        changed = [dict(item) for item in self.answers]
        changed[0]["choiceId"] = self.questions[0]["choices"][1]["id"]
        with self.conn:
            payload, status = server.save_daily_quiz_result(self.conn, self.user, "2026-09-09", "football", changed)
        self.assertEqual(status, 409)

    def test_progress_rejects_wrong_date_invalid_choice_and_out_of_order(self):
        for answers in ([], self.answers * 2, [{"questionId": "bad", "choiceId": "A"}], [self.answers[1]], [None]):
            self.assertEqual(self.save(answers)[1], 400)
        self.assertEqual(server.save_daily_quiz_progress(self.conn, self.user, "2026-09-08", "football", self.answers)[1], 400)
        self.assertEqual(server.save_daily_quiz_progress(self.conn, self.user, "2026-09-09", "invalid", self.answers)[1], 400)

    def test_today_status_tracks_progress_and_completion_without_starting_wordle(self):
        initial = playability.today_payload(self.conn, self.user, "2026-09-09")
        self.assertEqual(initial["activities"][0]["status"], "ready")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM wordle_results").fetchone()[0], 0)
        self.save(self.answers[:1])
        self.assertEqual(playability.today_payload(self.conn, self.user, "2026-09-09")["activities"][1]["status"], "continue")
        self.save(self.answers)
        self.assertEqual(playability.today_payload(self.conn, self.user, "2026-09-09")["activities"][1]["status"], "completed")
        self.assertEqual(initial["nextRoundAt"], "2026-09-10T00:00:00+00:00")

    def test_map_round_remains_available_and_keeps_progress_between_publication_days(self):
        self.assertEqual(daily_map_game.active_map_round_date("2026-09-10"), "2026-09-09")
        self.assertEqual(daily_map_game.active_map_round_date("2026-09-11"), "2026-09-09")
        self.assertEqual(daily_map_game.active_map_round_date("2026-09-12"), "2026-09-12")
        self.assertEqual(daily_map_game.active_map_round_date("2026-09-13"), "2026-09-12")
        self.assertEqual(daily_map_game.active_map_round_date("2026-09-15"), "2026-09-12")

        now = server.utc_now()
        puzzle_id = self.conn.execute(
            "INSERT INTO daily_map_puzzles (puzzle_date, status) VALUES ('2026-09-09', 'published')"
        ).lastrowid
        place_id = self.conn.execute("SELECT id FROM map_place_pool LIMIT 1").fetchone()["id"]
        level_id = self.conn.execute(
            "INSERT INTO daily_map_levels (puzzle_id, level_slug, place_id, max_points, lambda_km, created_at) "
            "VALUES (?, 'easy', ?, 10, 100, ?)",
            (puzzle_id, place_id, now),
        ).lastrowid
        self.conn.execute(
            "INSERT INTO daily_map_progress (user_id, level_id, revealed_hint_count, created_at, updated_at) "
            "VALUES (?, ?, 1, ?, ?)",
            (self.user, level_id, now, now),
        )
        thursday = next(item for item in playability.today_payload(self.conn, self.user, "2026-09-10")["activities"] if item["id"] == "map")
        self.assertEqual(thursday["status"], "continue")
        with patch.object(server, "today_game_date", return_value="2026-09-10"):
            status, bundle = self.route("GET", "/api/daily-map-game")
        self.assertEqual(status, 200)
        self.assertEqual(bundle["date"], "2026-09-09")
        self.assertEqual(bundle["levels"][0]["revealedHintCount"], 1)
        self.conn.execute(
            "INSERT INTO daily_map_guesses (user_id, level_id, guessed_lat, guessed_lng, revealed_hint_count, "
            "distance_m, score, band, completed_at, created_at, updated_at) "
            "VALUES (?, ?, 0, 0, 1, 0, 7, 'exact', ?, ?, ?)",
            (self.user, level_id, "2026-09-11T12:00:00+00:00", now, now),
        )
        friday = next(item for item in playability.today_payload(self.conn, self.user, "2026-09-11")["activities"] if item["id"] == "map")
        self.assertEqual((friday["status"], friday["score"]), ("completed", 7))

    def test_map_league_points_count_in_week_played_not_week_published(self):
        now = server.utc_now()
        puzzle_id = self.conn.execute(
            "INSERT INTO daily_map_puzzles (puzzle_date, status) VALUES ('2026-09-12', 'published')"
        ).lastrowid
        place_id = self.conn.execute("SELECT id FROM map_place_pool LIMIT 1").fetchone()["id"]
        level_id = self.conn.execute(
            "INSERT INTO daily_map_levels (puzzle_id, level_slug, place_id, max_points, lambda_km, created_at) "
            "VALUES (?, 'easy', ?, 10, 100, ?)",
            (puzzle_id, place_id, now),
        ).lastrowid
        self.conn.execute(
            "INSERT INTO daily_map_guesses (user_id, level_id, guessed_lat, guessed_lng, revealed_hint_count, "
            "distance_m, score, band, completed_at, created_at, updated_at) "
            "VALUES (?, ?, 0, 0, 0, 0, 10, 'exact', ?, ?, ?)",
            (self.user, level_id, "2026-09-14T12:00:00+00:00", now, now),
        )
        league = playability.league_payload(self.conn, "2026-09-14")
        player = next(item for item in league["players"] if item["id"] == self.user)
        self.assertEqual(player["games"]["map"], 10)
        self.assertEqual(player["points"], 10)
        second_puzzle_id = self.conn.execute(
            "INSERT INTO daily_map_puzzles (puzzle_date, status) VALUES ('2026-09-16', 'published')"
        ).lastrowid
        second_level_id = self.conn.execute(
            "INSERT INTO daily_map_levels (puzzle_id, level_slug, place_id, max_points, lambda_km, created_at) "
            "VALUES (?, 'easy', ?, 10, 100, ?)",
            (second_puzzle_id, place_id, now),
        ).lastrowid
        self.conn.execute(
            "INSERT INTO daily_map_guesses (user_id, level_id, guessed_lat, guessed_lng, revealed_hint_count, "
            "distance_m, score, band, completed_at, created_at, updated_at) "
            "VALUES (?, ?, 0, 0, 0, 0, 7, 'exact', ?, ?, ?)",
            (self.user, second_level_id, "2026-09-16T12:00:00+00:00", now, now),
        )
        two_rounds = playability.league_payload(self.conn, "2026-09-16")
        player = next(item for item in two_rounds["players"] if item["id"] == self.user)
        self.assertEqual(player["games"]["map"], 17)

    def test_balanced_league_preserves_raw_quiz_results(self):
        self.save(self.answers)
        league = playability.league_payload(self.conn, "2026-09-09")
        player = next(row for row in league["players"] if row["id"] == self.user)
        self.assertEqual(player["games"]["football"], 10)
        self.assertEqual(self.conn.execute("SELECT score FROM daily_quiz_results").fetchone()[0], 12)
        self.assertEqual((league["periodStart"], league["periodEnd"]), ("2026-09-07", "2026-09-13"))
        self.assertIsNone(next(row for row in league["players"] if row["id"] == self.other)["rank"])

    def test_wordle_mastery_bonus_does_not_affect_league(self):
        now = server.utc_now()
        game = self.conn.execute("INSERT INTO daily_wordle_games (game_date,secret_word,created_at) VALUES ('2026-09-09','arise',?)", (now,)).lastrowid
        for user, raw in ((self.user, 39), (self.other, 1)):
            self.conn.execute("INSERT INTO wordle_results (user_id,game_id,status,attempts_used,score,created_at,updated_at) VALUES (?,?,'won',6,?,?,?)", (user, game, raw, now, now))
        rows = playability.league_payload(self.conn, "2026-09-09")["players"]
        self.assertEqual([row["points"] for row in rows], [5, 5])
        self.assertEqual([row["rank"] for row in rows], [1, 1])
        self.assertEqual(self.conn.execute("SELECT SUM(score) FROM wordle_results").fetchone()[0], 40)

    def test_news_unchanged_poll_does_not_claim_new_update(self):
        payload = {"sourceKey": "story", "title": "An important result", "url": "https://example.com/story", "source": "Club", "summary": "First score", "publishedAt": "2026-09-09T12:00:00+00:00"}
        with patch.object(server, "utc_now", return_value="2026-09-09T12:00:00+00:00"):
            first, _ = server.upsert_news_item(self.conn, payload)
        with patch.object(server, "utc_now", return_value="2026-09-09T12:10:00+00:00"):
            unchanged, inserted = server.upsert_news_item(self.conn, payload)
            self.assertFalse(inserted)
            self.assertEqual(unchanged["updatedAt"], first["updatedAt"])
            changed, _ = server.upsert_news_item(self.conn, {**payload, "summary": "Corrected score"})
            self.assertNotEqual(changed["updatedAt"], first["updatedAt"])

    def route(self, method, path, query="", payload=None, user=True):
        responses = []
        handler = SimpleNamespace(
            headers={}, read_json=lambda: payload or {},
            send_json=lambda status, body: responses.append((status, body)),
            send_error_json=lambda status, error: responses.append((status, {"error": error})),
        )
        with patch.object(server, "connect_db", return_value=self.conn), patch.object(server, "get_cookie_value", return_value="test"), patch.object(server, "current_user", return_value={"id": self.user, "role": "user"} if user else None):
            server.FultonsHandler.route_api(handler, method, path, query)
        return responses[0]

    def test_practice_cannot_read_today_and_never_writes_league_results(self):
        self.assertEqual(self.route("GET", "/api/practice/quiz", "date=2026-09-09")[0], 404)
        self.conn.execute("UPDATE daily_quiz_sets SET quiz_date='2026-09-08' WHERE id=?", (self.quiz_id,))
        self.conn.commit()
        status, listed = self.route("GET", "/api/practice/quizzes")
        self.assertEqual(listed["dates"], ["2026-09-08"])
        status, public = self.route("GET", "/api/practice/quiz", "date=2026-09-08")
        self.assertEqual(status, 200)
        self.assertNotIn("correct_answer", json.dumps(public))
        status, result = self.route("POST", "/api/practice/quiz/result", payload={"date": "2026-09-08", "category": "football", "answers": self.answers})
        self.assertEqual(status, 200)
        self.assertEqual(result["result"]["correctCount"], 3)
        self.assertEqual(result["result"]["scoringVersion"], "practice-only")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM daily_quiz_results").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM daily_quiz_progress").fetchone()[0], 0)

    def test_new_player_endpoints_require_authentication(self):
        for path in ("/api/today", "/api/league", "/api/practice/quizzes", "/api/practice/quiz"):
            self.assertEqual(self.route("GET", path, user=False)[0], 401)

    def test_docker_contains_league_module(self):
        dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
        self.assertIn("COPY --chown=appuser:appuser playability.py ./", dockerfile)


if __name__ == "__main__":
    unittest.main()

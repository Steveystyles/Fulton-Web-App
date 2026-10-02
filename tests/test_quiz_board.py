import json
import hashlib
import sqlite3
import unittest

import daily_quiz
import quiz_board


class QuizBoardTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
        self.conn.execute("INSERT INTO users (id, username) VALUES (1, 'player')")
        daily_quiz.initialize_database(self.conn)
        quiz_board.initialize_database(self.conn)
        for day in ("2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05", "2026-10-06"):
            self._seed_day(day)

    def _seed_day(self, day):
        set_id = self.conn.execute(
            "INSERT INTO daily_quiz_sets (quiz_date,status,published_at) VALUES (?,'published','now')", (day,)
        ).lastrowid
        for subject in ("football", "general_knowledge"):
            for difficulty in ("easy", "medium", "hard"):
                answer = f"{subject}-{difficulty}-{day}"
                self.conn.execute(
                    """INSERT INTO daily_quiz_questions
                    (quiz_set_id,subject,difficulty,question,choices_json,correct_answer,explanation,
                     interesting_reason,tags_json,normalized_question,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (set_id, subject, difficulty, f"Question {answer}?", json.dumps([answer, "B", "C", "D"]),
                     answer, "Because it is correct.", "Worth knowing.", json.dumps(["history"]), answer, "now"),
                )
        self.conn.commit()

    def test_daily_board_hides_answers_and_scores_four_picks_against_fixed_maximum(self):
        board = quiz_board.ensure_board(self.conn, 1, "2026-09-29", "daily", "now")
        public = quiz_board.board_payload(self.conn, board)
        self.assertEqual(len(public["cards"]), 6)
        self.assertEqual(
            {(card["subject"], card["difficulty"]) for card in public["cards"]},
            {(subject, difficulty) for subject in ("football", "general") for difficulty in ("easy", "medium", "hard")},
        )
        self.assertNotIn("question", public["cards"][0])
        for _ in range(4):
            card = next(item for item in public["cards"] if item["selectedOrder"] is None)
            public = quiz_board.select_card(self.conn, board, card["id"], "now")
            active = next(item for item in public["cards"] if item.get("question"))
            answer = active["question"]["answers"][0]["id"]
            response = quiz_board.answer_card(self.conn, board, active["id"], answer, "now")
            self.assertIn("correctAnswer", response["adjudication"])
            public = response["board"]
            board = self.conn.execute("SELECT * FROM quiz_boards WHERE id=?", (board["id"],)).fetchone()
        self.assertEqual(public["status"], "completed")
        self.assertEqual(public["maxScore"], 19)
        self.assertEqual(public["bonusPoints"], 3)

    def test_unpicked_cards_return_to_equal_chance_pool(self):
        board = quiz_board.ensure_board(self.conn, 1, "2026-09-29", "daily", "now")
        public = quiz_board.board_payload(self.conn, board)
        for _ in range(4):
            card = next(item for item in public["cards"] if item["selectedOrder"] is None)
            public = quiz_board.select_card(self.conn, board, card["id"], "now")
            active = next(item for item in public["cards"] if item.get("question"))
            public = quiz_board.answer_card(
                self.conn, board, active["id"], active["question"]["answers"][0]["id"], "now"
            )["board"]
            board = self.conn.execute("SELECT * FROM quiz_boards WHERE id=?", (board["id"],)).fetchone()
        candidates = quiz_board._candidate_rows(self.conn, "2026-09-30", practice=False, user_id=1)
        unused = self.conn.execute(
            "SELECT question_id FROM quiz_board_cards WHERE board_id=? AND selected_order IS NULL", (board["id"],)
        ).fetchall()
        candidate_ids = {row["id"] for row in candidates}
        self.assertTrue({row["question_id"] for row in unused}.issubset(candidate_ids))
        self.assertTrue(all(row["prior_appearances"] == 1 for row in candidates if row["id"] in {item["question_id"] for item in unused}))
        self.assertTrue(all(row["id"] not in candidate_ids for row in self.conn.execute(
            "SELECT question_id AS id FROM quiz_board_cards WHERE board_id=? AND selected_order IS NOT NULL", (board["id"],)
        )))
        next_board = quiz_board.ensure_board(self.conn, 1, "2026-09-30", "daily", "later")
        expected = {}
        for row in candidates:
            slot = (row["subject"], row["difficulty"])
            rank = hashlib.sha256(f"1:2026-09-30:{row['subject']}:{row['difficulty']}:{row['id']}".encode()).digest()
            if slot not in expected or rank < expected[slot][0]:
                expected[slot] = (rank, row["id"])
        actual = {tuple(row[key] for key in ("subject", "difficulty")): row["question_id"] for row in self.conn.execute(
            """SELECT q.subject, q.difficulty, c.question_id FROM quiz_board_cards c
               JOIN daily_quiz_questions q ON q.id=c.question_id WHERE c.board_id=?""", (next_board["id"],)
        )}
        self.assertEqual(actual, {slot: item[1] for slot, item in expected.items()})

    def test_practice_board_has_one_card_per_subject_and_difficulty(self):
        board = quiz_board.ensure_board(self.conn, 1, "2026-09-30", "practice", "now")
        cards = quiz_board.board_payload(self.conn, board)["cards"]
        self.assertEqual(len(cards), 6)
        self.assertEqual(
            {(card["subject"], card["difficulty"]) for card in cards},
            {(subject, difficulty) for subject in ("football", "general") for difficulty in ("easy", "medium", "hard")},
        )

    def test_card_previews_use_question_text_instead_of_generic_tags(self):
        question_id = self.conn.execute("SELECT id FROM daily_quiz_questions WHERE subject='football' LIMIT 1").fetchone()["id"]
        self.conn.execute(
            "UPDATE daily_quiz_questions SET question=?, tags_json=? WHERE id=?",
            ("Which Dutch club played its home matches at De Meer Stadium?", json.dumps(["Dutch-Football", "Football"]), question_id),
        )
        row = self.conn.execute("SELECT * FROM daily_quiz_questions WHERE id=?", (question_id,)).fetchone()
        self.assertEqual(quiz_board._teaser(row), "Which Dutch club played its home matches at De Meer Stadium?")

    def test_card_preview_hides_answer_when_question_contains_it(self):
        question_id = self.conn.execute("SELECT id FROM daily_quiz_questions WHERE subject='football' LIMIT 1").fetchone()["id"]
        self.conn.execute(
            "UPDATE daily_quiz_questions SET question=?, correct_answer=?, tags_json=? WHERE id=?",
            ("Did Ajax win this match?", "Ajax", json.dumps(["Ajax", "Dutch-Football"]), question_id),
        )
        row = self.conn.execute("SELECT * FROM daily_quiz_questions WHERE id=?", (question_id,)).fetchone()
        self.assertEqual(quiz_board._teaser(row), "A question about dutch football")

    def test_practice_replays_an_answered_question_when_one_slot_has_no_unused_questions(self):
        answered_ids = []
        for day in ("2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05"):
            question_id = self.conn.execute(
                """SELECT q.id FROM daily_quiz_questions q JOIN daily_quiz_sets s ON s.id = q.quiz_set_id
                   WHERE s.quiz_date = ? AND q.subject = 'general_knowledge' AND q.difficulty = 'hard'""",
                (day,),
            ).fetchone()["id"]
            board_id = self.conn.execute(
                """INSERT INTO quiz_boards (user_id, game_date, mode, status, created_at, updated_at)
                   VALUES (1, ?, 'daily', 'completed', 'now', 'now')""",
                (day,),
            ).lastrowid
            self.conn.execute(
                """INSERT INTO quiz_board_cards
                   (board_id, question_id, position, source_kind, selected_order, answered_at)
                   VALUES (?, ?, 0, 'new', 1, 'now')""",
                (board_id, question_id),
            )
            answered_ids.append(question_id)

        board = quiz_board.ensure_board(self.conn, 1, "2026-10-06", "practice", "now")
        cards = quiz_board.board_payload(self.conn, board)["cards"]
        self.assertEqual(len({(card["subject"], card["difficulty"]) for card in cards}), 6)
        replayed = next(card for card in cards if card["subject"] == "general" and card["difficulty"] == "hard")
        replayed_question_id = self.conn.execute(
            "SELECT question_id FROM quiz_board_cards WHERE id = ?",
            (int(replayed["id"].removeprefix("card_")),),
        ).fetchone()["question_id"]
        self.assertIn(replayed_question_id, answered_ids)

    def test_existing_balanced_board_updates_the_obsolete_maximum(self):
        board = quiz_board.ensure_board(self.conn, 1, "2026-09-29", "daily", "now")
        self.conn.execute("UPDATE quiz_boards SET max_score = 23 WHERE id = ?", (board["id"],))
        current = quiz_board.ensure_board(self.conn, 1, "2026-09-29", "daily", "later")
        self.assertEqual(quiz_board.board_payload(self.conn, current)["maxScore"], 19)

    def test_existing_unplayed_board_repairs_duplicate_difficulty_on_reload(self):
        board = quiz_board.ensure_board(self.conn, 1, "2026-09-29", "daily", "now")
        hard_card = self.conn.execute(
            """SELECT c.id FROM quiz_board_cards c JOIN daily_quiz_questions q ON q.id = c.question_id
               WHERE c.board_id = ? AND q.subject = 'football' AND q.difficulty = 'hard'""",
            (board["id"],),
        ).fetchone()
        duplicate_easy = self.conn.execute(
            """SELECT q.id FROM daily_quiz_questions q JOIN daily_quiz_sets s ON s.id = q.quiz_set_id
               WHERE s.quiz_date = '2026-09-30' AND q.subject = 'football' AND q.difficulty = 'easy'"""
        ).fetchone()
        self.conn.execute(
            "UPDATE quiz_board_cards SET question_id = ? WHERE id = ?",
            (duplicate_easy["id"], hard_card["id"]),
        )
        repaired = quiz_board.ensure_board(self.conn, 1, "2026-09-29", "daily", "later")
        cards = quiz_board.board_payload(self.conn, repaired)["cards"]
        self.assertEqual(len({(card["subject"], card["difficulty"]) for card in cards}), 6)
        self.assertEqual(sum(card["difficulty"] == "hard" for card in cards), 2)
        self.assertEqual(quiz_board.board_payload(self.conn, repaired)["maxScore"], 19)

    def test_repair_preserves_an_answered_card_and_replaces_only_unplayed_duplicates(self):
        board = quiz_board.ensure_board(self.conn, 1, "2026-09-29", "daily", "now")
        public = quiz_board.board_payload(self.conn, board)
        played = public["cards"][0]
        public = quiz_board.select_card(self.conn, board, played["id"], "now")
        answer = next(card for card in public["cards"] if card.get("question"))["question"]["answers"][0]["id"]
        quiz_board.answer_card(self.conn, board, played["id"], answer, "now")
        hard_card = self.conn.execute(
            """SELECT c.id FROM quiz_board_cards c JOIN daily_quiz_questions q ON q.id = c.question_id
               WHERE c.board_id = ? AND q.subject = 'football' AND q.difficulty = 'hard'""",
            (board["id"],),
        ).fetchone()
        duplicate_easy = self.conn.execute(
            """SELECT q.id FROM daily_quiz_questions q JOIN daily_quiz_sets s ON s.id = q.quiz_set_id
               WHERE s.quiz_date = '2026-09-30' AND q.subject = 'football' AND q.difficulty = 'easy'"""
        ).fetchone()
        self.conn.execute("UPDATE quiz_board_cards SET question_id = ? WHERE id = ?", (duplicate_easy["id"], hard_card["id"]))
        current = self.conn.execute("SELECT * FROM quiz_boards WHERE id = ?", (board["id"],)).fetchone()
        repaired = quiz_board.ensure_board(self.conn, 1, "2026-09-29", "daily", "later")
        cards = quiz_board.board_payload(self.conn, repaired)["cards"]
        self.assertEqual(len({(card["subject"], card["difficulty"]) for card in cards}), 6)
        self.assertEqual(sum(card["answered"] for card in cards), 1)
        self.assertTrue(next(card for card in cards if card["id"] == played["id"])["answered"])
        self.assertEqual(current["status"], "in_progress")

    def test_many_prior_unplayed_appearances_do_not_expire_a_question(self):
        question_id = self.conn.execute("SELECT id FROM daily_quiz_questions LIMIT 1").fetchone()["id"]
        for day in ("2026-09-20", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-26", "2026-09-27"):
            board_id = self.conn.execute(
                """INSERT INTO quiz_boards (user_id, game_date, mode, created_at, updated_at)
                   VALUES (1, ?, 'daily', 'now', 'now')""", (day,),
            ).lastrowid
            self.conn.execute(
                """INSERT INTO quiz_board_cards (board_id, question_id, position, source_kind, appearances)
                   VALUES (?, ?, 0, 'carry', 1)""", (board_id, question_id),
            )
        candidates = quiz_board._candidate_rows(self.conn, "2026-09-30", practice=False, user_id=1)
        returned = next(row for row in candidates if row["id"] == question_id)
        self.assertEqual(returned["prior_appearances"], 8)

    def test_missing_difficulty_slot_fails_instead_of_showing_another_easy_card(self):
        self.conn.execute(
            """DELETE FROM daily_quiz_questions WHERE subject = 'general_knowledge' AND difficulty = 'hard'"""
        )
        with self.assertRaisesRegex(LookupError, "one per subject and difficulty"):
            quiz_board.ensure_board(self.conn, 1, "2026-09-29", "daily", "now")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM quiz_boards").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()

import json
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
        for day in ("2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05"):
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
        self.assertEqual(public["maxScore"], 23)
        self.assertEqual(public["bonusPoints"], 3)

    def test_two_unpicked_cards_roll_once_to_next_daily_board(self):
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
        next_board = quiz_board.ensure_board(self.conn, 1, "2026-09-30", "daily", "later")
        next_public = quiz_board.board_payload(self.conn, next_board)
        carries = [item for item in next_public["cards"] if item["source"] == "carry"]
        self.assertEqual(len(carries), 2)
        self.assertEqual({item["appearances"] for item in carries}, {2})


if __name__ == "__main__":
    unittest.main()

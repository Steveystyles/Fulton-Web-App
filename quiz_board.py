"""Per-player daily and practice quiz boards built from verified quiz questions."""
from __future__ import annotations

from datetime import date, timedelta
import json
import sqlite3
from typing import Any

import daily_quiz


POINTS = {"easy": 1, "medium": 3, "hard": 5}
DAILY_CARD_COUNT = 6
DAILY_PICK_COUNT = 4
DAILY_MAX_SCORE = 23
PERFECT_BONUS = 3
MAX_APPEARANCES = 7
LAUNCH_RESERVE_CARDS = 34


def initialize_database(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS quiz_boards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            game_date TEXT NOT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('daily', 'practice')),
            status TEXT NOT NULL DEFAULT 'ready' CHECK (status IN ('ready', 'in_progress', 'completed')),
            score INTEGER NOT NULL DEFAULT 0,
            max_score INTEGER NOT NULL DEFAULT 23,
            correct_count INTEGER NOT NULL DEFAULT 0,
            bonus_points INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            UNIQUE (user_id, game_date, mode)
        );

        CREATE TABLE IF NOT EXISTS quiz_board_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board_id INTEGER NOT NULL REFERENCES quiz_boards(id) ON DELETE CASCADE,
            question_id INTEGER NOT NULL REFERENCES daily_quiz_questions(id),
            position INTEGER NOT NULL,
            source_kind TEXT NOT NULL CHECK (source_kind IN ('new', 'carry', 'practice')),
            appearances INTEGER NOT NULL DEFAULT 1,
            selected_order INTEGER,
            choice_id TEXT,
            correct INTEGER,
            points_awarded INTEGER NOT NULL DEFAULT 0,
            answered_at TEXT,
            UNIQUE (board_id, position),
            UNIQUE (board_id, question_id)
        );

        CREATE INDEX IF NOT EXISTS idx_quiz_board_cards_question
        ON quiz_board_cards(question_id, board_id);

        CREATE TABLE IF NOT EXISTS game_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            game_date TEXT NOT NULL,
            game TEXT NOT NULL CHECK (game IN ('quiz', 'map')),
            rating TEXT NOT NULL CHECK (rating IN ('fun', 'fair', 'too_hard', 'unclear')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (user_id, game_date, game)
        );

        CREATE TABLE IF NOT EXISTS product_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            game_date TEXT NOT NULL,
            event_type TEXT NOT NULL,
            game TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_product_events_date
        ON product_events(game_date, event_type);

        CREATE TABLE IF NOT EXISTS weekly_summary_deliveries (
            week_start TEXT PRIMARY KEY,
            delivered_at TEXT NOT NULL
        );
        """
    )


def _question_rows(conn: sqlite3.Connection, question_ids: list[int]) -> dict[int, sqlite3.Row]:
    if not question_ids:
        return {}
    bounded_ids = question_ids[:DAILY_CARD_COUNT]
    padded_ids = bounded_ids + [-1] * (DAILY_CARD_COUNT - len(bounded_ids))
    rows = conn.execute(
        "SELECT * FROM daily_quiz_questions WHERE id IN (?, ?, ?, ?, ?, ?)", padded_ids
    ).fetchall()
    return {int(row["id"]): row for row in rows}


def _candidate_rows(conn: sqlite3.Connection, game_date: str, *, practice: bool, user_id: int) -> list[sqlite3.Row]:
    if practice:
        rows = conn.execute(
            """
            SELECT q.*
            FROM daily_quiz_questions q
            JOIN daily_quiz_sets s ON s.id = q.quiz_set_id
            WHERE s.status = 'published' AND s.quiz_date < ?
              AND NOT EXISTS (
                SELECT 1 FROM quiz_board_cards c
                JOIN quiz_boards b ON b.id = c.board_id
                WHERE b.user_id = ? AND c.question_id = q.id AND c.answered_at IS NOT NULL
              )
            ORDER BY s.quiz_date ASC, q.id ASC
            """,
            (game_date, user_id),
        ).fetchall()
        if len(rows) >= DAILY_CARD_COUNT:
            return rows
        return conn.execute(
            """
            SELECT q.* FROM daily_quiz_questions q
            JOIN daily_quiz_sets s ON s.id = q.quiz_set_id
            WHERE s.status = 'published' AND s.quiz_date < ?
            ORDER BY s.quiz_date ASC, q.id ASC
            """,
            (game_date,),
        ).fetchall()
    return conn.execute(
        """
        SELECT q.* FROM daily_quiz_questions q
        JOIN daily_quiz_sets s ON s.id = q.quiz_set_id
        WHERE s.status = 'published' AND s.quiz_date >= ?
        ORDER BY CASE WHEN s.quiz_date = ? THEN 0 ELSE 1 END,
                 s.quiz_date ASC,
                 CASE q.difficulty WHEN 'easy' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                 q.subject ASC, q.id ASC
        """,
        (game_date, game_date),
    ).fetchall()


def ensure_board(conn: sqlite3.Connection, user_id: int, game_date: str, mode: str, now: str) -> sqlite3.Row:
    if mode not in {"daily", "practice"}:
        raise ValueError("Quiz mode must be daily or practice.")
    existing = conn.execute(
        "SELECT * FROM quiz_boards WHERE user_id=? AND game_date=? AND mode=?",
        (user_id, game_date, mode),
    ).fetchone()
    if existing is not None:
        return existing
    if mode == "daily":
        reserve_count = conn.execute(
            """SELECT COUNT(*) FROM daily_quiz_questions q
               JOIN daily_quiz_sets s ON s.id=q.quiz_set_id
               WHERE s.status='published' AND s.quiz_date >= ?""",
            (game_date,),
        ).fetchone()[0]
        if int(reserve_count) < LAUNCH_RESERVE_CARDS:
            raise LookupError(
                f"The new quiz is preparing its verified reserve ({reserve_count}/{LAUNCH_RESERVE_CARDS} cards)."
            )
    cursor = conn.execute(
        """INSERT INTO quiz_boards
           (user_id, game_date, mode, status, score, max_score, correct_count, bonus_points, created_at, updated_at)
           VALUES (?, ?, ?, 'ready', 0, ?, 0, 0, ?, ?)""",
        (user_id, game_date, mode, DAILY_MAX_SCORE, now, now),
    )
    board_id = int(cursor.lastrowid)
    chosen: list[tuple[int, str, int]] = []
    if mode == "daily":
        yesterday = (date.fromisoformat(game_date) - timedelta(days=1)).isoformat()
        leftovers = conn.execute(
            """
            SELECT c.question_id, c.appearances
            FROM quiz_board_cards c JOIN quiz_boards b ON b.id=c.board_id
            WHERE b.user_id=? AND b.game_date=? AND b.mode='daily'
              AND c.selected_order IS NULL AND c.appearances < ?
            ORDER BY c.position LIMIT 2
            """,
            (user_id, yesterday, MAX_APPEARANCES),
        ).fetchall()
        chosen.extend((int(row["question_id"]), "carry", int(row["appearances"]) + 1) for row in leftovers)
    candidates = _candidate_rows(conn, game_date, practice=mode == "practice", user_id=user_id)
    used = {item[0] for item in chosen}
    source = "practice" if mode == "practice" else "new"
    for row in candidates:
        question_id = int(row["id"])
        if question_id in used:
            continue
        chosen.append((question_id, source, MAX_APPEARANCES if mode == "practice" else 1))
        used.add(question_id)
        if len(chosen) == DAILY_CARD_COUNT:
            break
    if len(chosen) < DAILY_CARD_COUNT:
        conn.execute("DELETE FROM quiz_boards WHERE id=?", (board_id,))
        raise LookupError("Six verified quiz cards are not available yet.")
    for position, (question_id, source_kind, appearances) in enumerate(chosen):
        conn.execute(
            """INSERT INTO quiz_board_cards
               (board_id, question_id, position, source_kind, appearances)
               VALUES (?, ?, ?, ?, ?)""",
            (board_id, question_id, position, source_kind, appearances),
        )
    return conn.execute("SELECT * FROM quiz_boards WHERE id=?", (board_id,)).fetchone()


def _teaser(row: sqlite3.Row) -> str:
    try:
        tags = [str(tag).replace("_", " ").strip() for tag in json.loads(row["tags_json"] or "[]")]
    except (TypeError, json.JSONDecodeError):
        tags = []
    safe_tag = next((tag for tag in tags if 2 <= len(tag) <= 32), "")
    subject = "Football" if row["subject"] == "football" else "General knowledge"
    return f"{subject} · {safe_tag.title()}" if safe_tag else f"{subject} · A fresh challenge"


def _public_question(row: sqlite3.Row) -> dict[str, Any]:
    question_id = int(row["id"])
    choices = json.loads(row["choices_json"])
    return {
        "id": daily_quiz.public_question_id(question_id),
        "difficulty": row["difficulty"],
        "question": daily_quiz.display_text(row["question"]),
        "answers": [
            {"id": daily_quiz.public_choice_id(question_id, index), "text": daily_quiz.display_text(choice)}
            for index, choice in enumerate(choices)
        ],
    }


def board_payload(conn: sqlite3.Connection, board: sqlite3.Row) -> dict[str, Any]:
    cards = conn.execute(
        "SELECT * FROM quiz_board_cards WHERE board_id=? ORDER BY position", (board["id"],)
    ).fetchall()
    questions = _question_rows(conn, [int(card["question_id"]) for card in cards])
    output = []
    for card in cards:
        question = questions[int(card["question_id"])]
        selected = card["selected_order"] is not None
        answered = card["answered_at"] is not None
        item: dict[str, Any] = {
            "id": f"card_{card['id']}",
            "subject": "football" if question["subject"] == "football" else "general",
            "difficulty": question["difficulty"],
            "points": POINTS[str(question["difficulty"])],
            "teaser": _teaser(question),
            "source": card["source_kind"],
            "appearances": card["appearances"],
            "selectedOrder": card["selected_order"],
            "answered": answered,
        }
        if selected and not answered:
            item["question"] = _public_question(question)
        output.append(item)
    return {
        "date": board["game_date"],
        "mode": board["mode"],
        "status": board["status"],
        "pickCount": DAILY_PICK_COUNT,
        "selectedCount": sum(card["selected_order"] is not None for card in cards),
        "answeredCount": sum(card["answered_at"] is not None for card in cards),
        "score": board["score"],
        "maxScore": board["max_score"],
        "correctCount": board["correct_count"],
        "bonusPoints": board["bonus_points"],
        "completedAt": board["completed_at"],
        "cards": output,
    }


def select_card(conn: sqlite3.Connection, board: sqlite3.Row, public_card_id: str, now: str) -> dict[str, Any]:
    if board["status"] == "completed":
        return board_payload(conn, board)
    conn.execute("UPDATE quiz_boards SET updated_at=updated_at WHERE id=?", (board["id"],))
    try:
        card_id = int(public_card_id.removeprefix("card_"))
    except ValueError as error:
        raise ValueError("Choose a valid quiz card.") from error
    card = conn.execute(
        "SELECT * FROM quiz_board_cards WHERE id=? AND board_id=?", (card_id, board["id"])
    ).fetchone()
    if card is None:
        raise ValueError("Choose a valid quiz card.")
    active = conn.execute(
        "SELECT id FROM quiz_board_cards WHERE board_id=? AND selected_order IS NOT NULL AND answered_at IS NULL",
        (board["id"],),
    ).fetchone()
    if active is not None and int(active["id"]) != card_id:
        raise ValueError("Answer the selected card before choosing another.")
    if card["selected_order"] is None:
        count = conn.execute(
            "SELECT COUNT(*) FROM quiz_board_cards WHERE board_id=? AND selected_order IS NOT NULL",
            (board["id"],),
        ).fetchone()[0]
        if count >= DAILY_PICK_COUNT:
            raise ValueError("This board already has four selected cards.")
        conn.execute(
            "UPDATE quiz_board_cards SET selected_order=? WHERE id=?", (count + 1, card_id)
        )
        conn.execute(
            "UPDATE quiz_boards SET status='in_progress', updated_at=? WHERE id=?", (now, board["id"])
        )
        conn.execute(
            "INSERT INTO product_events (user_id, game_date, event_type, game, metadata_json, created_at) VALUES (?, ?, 'card_selected', 'quiz', '{}', ?)",
            (board["user_id"], board["game_date"], now),
        )
    updated = conn.execute("SELECT * FROM quiz_boards WHERE id=?", (board["id"],)).fetchone()
    return board_payload(conn, updated)


def answer_card(conn: sqlite3.Connection, board: sqlite3.Row, public_card_id: str, choice_id: str, now: str) -> dict[str, Any]:
    conn.execute("UPDATE quiz_boards SET updated_at=updated_at WHERE id=?", (board["id"],))
    try:
        card_id = int(public_card_id.removeprefix("card_"))
    except ValueError as error:
        raise ValueError("Choose a valid quiz card.") from error
    card = conn.execute(
        "SELECT * FROM quiz_board_cards WHERE id=? AND board_id=? AND selected_order IS NOT NULL",
        (card_id, board["id"]),
    ).fetchone()
    if card is None:
        raise ValueError("Select this card before answering it.")
    question = conn.execute("SELECT * FROM daily_quiz_questions WHERE id=?", (card["question_id"],)).fetchone()
    if card["answered_at"] is not None:
        raise ValueError("That card has already been answered.")
    choices = json.loads(question["choices_json"])
    allowed = {daily_quiz.public_choice_id(int(question["id"]), index): choice for index, choice in enumerate(choices)}
    if choice_id not in allowed:
        raise ValueError("Choose one of this card's answers.")
    correct = allowed[choice_id] == question["correct_answer"]
    points = POINTS[str(question["difficulty"])] if correct else 0
    conn.execute(
        "UPDATE quiz_board_cards SET choice_id=?, correct=?, points_awarded=?, answered_at=? WHERE id=?",
        (choice_id, int(correct), points, now, card_id),
    )
    totals = conn.execute(
        "SELECT SUM(CASE WHEN answered_at IS NOT NULL THEN 1 ELSE 0 END) AS answered, SUM(COALESCE(correct,0)) AS correct_count, SUM(points_awarded) AS score FROM quiz_board_cards WHERE board_id=?",
        (board["id"],),
    ).fetchone()
    completed = int(totals["answered"]) == DAILY_PICK_COUNT
    bonus = PERFECT_BONUS if completed and int(totals["correct_count"] or 0) == DAILY_PICK_COUNT else 0
    conn.execute(
        """UPDATE quiz_boards SET status=?, score=?, correct_count=?, bonus_points=?,
           completed_at=CASE WHEN ? THEN ? ELSE completed_at END, updated_at=? WHERE id=?""",
        ("completed" if completed else "in_progress", int(totals["score"] or 0) + bonus,
         int(totals["correct_count"] or 0), bonus, int(completed), now, now, board["id"]),
    )
    conn.execute(
        "INSERT INTO product_events (user_id, game_date, event_type, game, metadata_json, created_at) VALUES (?, ?, 'card_answered', 'quiz', ?, ?)",
        (board["user_id"], board["game_date"], json.dumps({"correct": correct, "difficulty": question["difficulty"]}), now),
    )
    updated = conn.execute("SELECT * FROM quiz_boards WHERE id=?", (board["id"],)).fetchone()
    return {
        "adjudication": {
            "cardId": public_card_id,
            "correct": correct,
            "correctAnswer": daily_quiz.display_text(question["correct_answer"]),
            "explanation": daily_quiz.display_text(question["explanation"]),
            "interestingReason": daily_quiz.display_text(question["interesting_reason"]),
            "pointsAwarded": points,
        },
        "board": board_payload(conn, updated),
    }


def save_feedback(conn: sqlite3.Connection, user_id: int, game_date: str, game: str, rating: str, now: str) -> None:
    if game not in {"quiz", "map"} or rating not in {"fun", "fair", "too_hard", "unclear"}:
        raise ValueError("Choose a valid feedback option.")
    conn.execute(
        """INSERT INTO game_feedback (user_id, game_date, game, rating, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, game_date, game) DO UPDATE SET rating=excluded.rating, updated_at=excluded.updated_at""",
        (user_id, game_date, game, rating, now, now),
    )


def admin_report(conn: sqlite3.Connection, start: str, end: str) -> dict[str, Any]:
    boards = conn.execute(
        """SELECT COUNT(*) AS started,
                  SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
                  AVG(CASE WHEN status='completed' THEN score END) AS average_score
           FROM quiz_boards WHERE mode='daily' AND game_date BETWEEN ? AND ?""",
        (start, end),
    ).fetchone()
    feedback = [dict(row) for row in conn.execute(
        """SELECT game, rating, COUNT(*) AS count FROM game_feedback
           WHERE game_date BETWEEN ? AND ? GROUP BY game, rating ORDER BY game, rating""",
        (start, end),
    )]
    cards = [dict(row) for row in conn.execute(
        """SELECT q.subject, q.difficulty, COUNT(*) AS answers,
                  SUM(CASE WHEN c.correct=1 THEN 1 ELSE 0 END) AS correct
           FROM quiz_board_cards c JOIN quiz_boards b ON b.id=c.board_id
           JOIN daily_quiz_questions q ON q.id=c.question_id
           WHERE b.mode='daily' AND b.game_date BETWEEN ? AND ? AND c.answered_at IS NOT NULL
           GROUP BY q.subject, q.difficulty ORDER BY q.subject, q.difficulty""",
        (start, end),
    )]
    started = int(boards["started"] or 0)
    completed = int(boards["completed"] or 0)
    wordle = conn.execute(
        """SELECT COUNT(*) AS started,
                  SUM(CASE WHEN r.status IN ('won','lost') THEN 1 ELSE 0 END) AS completed
           FROM wordle_results r JOIN daily_wordle_games g ON g.id=r.game_id
           WHERE g.game_date BETWEEN ? AND ?""", (start, end)
    ).fetchone()
    map_started = conn.execute(
        """SELECT COUNT(DISTINCT p.user_id || ':' || d.puzzle_date) AS count
           FROM daily_map_progress p JOIN daily_map_levels l ON l.id=p.level_id
           JOIN daily_map_puzzles d ON d.id=l.puzzle_id WHERE d.puzzle_date BETWEEN ? AND ?""",
        (start, end),
    ).fetchone()[0]
    map_completed = conn.execute(
        """SELECT COUNT(*) FROM (
             SELECT g.user_id, d.puzzle_date
             FROM daily_map_guesses g JOIN daily_map_levels l ON l.id=g.level_id
             JOIN daily_map_puzzles d ON d.id=l.puzzle_id
             WHERE d.puzzle_date BETWEEN ? AND ?
             GROUP BY g.user_id, d.puzzle_date
             HAVING COUNT(*) = (SELECT COUNT(*) FROM daily_map_levels all_levels WHERE all_levels.puzzle_id=d.id)
           )""",
        (start, end),
    ).fetchone()[0]
    def journey(game: str, game_started: int, game_completed: int) -> dict[str, Any]:
        return {"game": game, "started": game_started, "completed": game_completed,
                "abandoned": max(0, game_started - game_completed),
                "completionRate": round(game_completed / game_started, 3) if game_started else 0}
    return {
        "periodStart": start,
        "periodEnd": end,
        "quiz": {"started": started, "completed": completed,
                 "completionRate": round(completed / started, 3) if started else 0,
                 "averageScore": round(float(boards["average_score"] or 0), 2)},
        "cards": cards,
        "feedback": feedback,
        "reserve": {
            "cards": int(conn.execute(
                """SELECT COUNT(*) FROM daily_quiz_questions q JOIN daily_quiz_sets s ON s.id=q.quiz_set_id
                   WHERE s.status='published' AND s.quiz_date >= ?""", (end,)
            ).fetchone()[0]),
            "launchTarget": LAUNCH_RESERVE_CARDS,
        },
        "journey": [
            journey("wordle", int(wordle["started"] or 0), int(wordle["completed"] or 0)),
            journey("quiz", started, completed),
            journey("map", int(map_started or 0), int(map_completed or 0)),
        ],
    }

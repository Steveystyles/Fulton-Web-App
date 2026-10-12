"""Read-only daily hub and balanced league projections. Original scores never change."""
from datetime import date, datetime, time, timedelta, timezone
import json
import quiz_board
import daily_map_game


def today_payload(conn, user_id, game_date, tz=timezone.utc):
    wordle = conn.execute(
        "SELECT r.status, r.attempts_used, r.score FROM wordle_results r "
        "JOIN daily_wordle_games g ON g.id = r.game_id WHERE r.user_id = ? AND g.game_date = ?",
        (user_id, game_date),
    ).fetchone()
    activities = [{"id": "wordle", "title": "Wordle", "href": "/wordle",
                   "status": ("completed" if wordle["status"] != "in_progress" else "continue") if wordle else "ready",
                   "score": wordle["score"] if wordle else None}]
    board = conn.execute(
        "SELECT status, score FROM quiz_boards WHERE user_id=? AND game_date=? AND mode='daily'",
        (user_id, game_date),
    ).fetchone()
    legacy_results = conn.execute(
        "SELECT score FROM daily_quiz_results WHERE user_id=? AND game_date=?",
        (user_id, game_date),
    ).fetchall()
    legacy_progress = conn.execute(
        "SELECT answers_json FROM daily_quiz_progress WHERE user_id=? AND game_date=?",
        (user_id, game_date),
    ).fetchall()
    available = quiz_board.daily_board_available(conn, user_id, game_date)
    activities.append({"id": "quiz", "title": "Quiz", "href": "/quiz",
                       "status": "completed" if (board and board["status"] == "completed") or legacy_results else "continue" if (board and board["status"] == "in_progress") or any(json.loads(row["answers_json"] or "[]") for row in legacy_progress) else "ready" if available else "unavailable",
                       "score": board["score"] if board and board["status"] == "completed" else sum(row["score"] for row in legacy_results) if legacy_results else None})
    active_map_date = daily_map_game.playable_map_round_date(conn, game_date)
    levels = conn.execute(
        "SELECT l.id, g.score, p.revealed_hint_count FROM daily_map_levels l "
        "JOIN daily_map_puzzles d ON d.id = l.puzzle_id "
        "LEFT JOIN daily_map_guesses g ON g.level_id = l.id AND g.user_id = ? "
        "LEFT JOIN daily_map_progress p ON p.level_id = l.id AND p.user_id = ? "
        "WHERE d.puzzle_date = ? AND d.status = 'published'", (user_id, user_id, active_map_date),
    ).fetchall()
    complete = bool(levels) and all(row["score"] is not None for row in levels)
    activities.append({"id": "map", "title": "Pin the place", "href": "/map",
                       "status": "completed" if complete else "continue" if any(row["revealed_hint_count"] or row["score"] is not None for row in levels) else "ready" if levels else "unavailable",
                       "score": sum(row["score"] or 0 for row in levels) if complete else None})
    tomorrow = date.fromisoformat(game_date) + timedelta(days=1)
    upcoming_map_dates = []
    cursor = date.fromisoformat(game_date)
    while len(upcoming_map_dates) < 2:
        cursor += timedelta(days=1)
        if cursor.weekday() in {2, 5}:
            upcoming_map_dates.append(cursor.isoformat())
    return {"date": game_date, "mapRoundDate": active_map_date,
            "nextRoundAt": datetime.combine(tomorrow, time(), tz).isoformat(),
            "activities": activities, "nextMapDates": upcoming_map_dates}


def league_period(conn, start, end, tz=timezone.utc):
    # Work in hundredths of a point to avoid floating-point tie differences.
    map_start_utc = datetime.combine(date.fromisoformat(start), time(), tz).astimezone(timezone.utc).isoformat()
    map_end_utc = datetime.combine(date.fromisoformat(end) + timedelta(days=1), time(), tz).astimezone(timezone.utc).isoformat()
    players = {row["id"]: {"id": row["id"], "username": row["username"],
               "games": {key: 0 for key in ("wordle", "quiz", "map", "football", "general")}}
               for row in conn.execute("SELECT id, username FROM users")}
    def add(user_id, game, units):
        if user_id in players:
            players[user_id]["games"][game] += units
    for row in conn.execute(
        "SELECT r.user_id, r.status, r.attempts_used FROM wordle_results r "
        "JOIN daily_wordle_games g ON g.id = r.game_id WHERE g.game_date BETWEEN ? AND ?", (start, end)
    ):
        add(row["user_id"], "wordle", max(0, 1100 - row["attempts_used"] * 100) if row["status"] == "won" and 1 <= row["attempts_used"] <= 6 else 0)
    for row in conn.execute("SELECT user_id, category, score, max_score FROM daily_quiz_results WHERE game_date BETWEEN ? AND ?", (start, end)):
        units = min(1000, max(0, round(row["score"] * 1000 / row["max_score"]))) if row["max_score"] else 0
        add(row["user_id"], "quiz", units)
        add(row["user_id"], row["category"], units)
    for row in conn.execute("SELECT user_id, score, max_score FROM quiz_boards WHERE mode='daily' AND status='completed' AND game_date BETWEEN ? AND ?", (start, end)):
        add(row["user_id"], "quiz", min(1000, max(0, round(row["score"] * 1000 / row["max_score"]))) if row["max_score"] else 0)
    for row in conn.execute(
        "SELECT g.user_id, SUM(g.score) AS score FROM daily_map_guesses g "
        "JOIN daily_map_levels l ON l.id = g.level_id "
        "WHERE julianday(g.completed_at) >= julianday(?) "
        "AND julianday(g.completed_at) < julianday(?) GROUP BY g.user_id, l.puzzle_id", (map_start_utc, map_end_utc)
    ):
        add(row["user_id"], "map", min(1000, max(0, row["score"] * 100)))
    total_units = lambda player: sum(player["games"][key] for key in ("wordle", "quiz", "map"))
    ordered = sorted(players.values(), key=lambda player: (-total_units(player), player["username"].casefold()))
    last_score, rank = None, 0
    for index, player in enumerate(ordered):
        units = total_units(player)
        if units != last_score:
            rank = index + 1
        last_score = units
        player.update(rank=rank if units else None, points=units / 100)
        player["games"] = {key: value / 100 for key, value in player["games"].items()}
    return ordered


def league_payload(conn, game_date, tz=timezone.utc):
    today = date.fromisoformat(game_date)
    monday = today - timedelta(days=today.weekday())
    previous = league_period(conn, (monday - timedelta(days=7)).isoformat(), (monday - timedelta(days=1)).isoformat(), tz)
    return {"periodStart": monday.isoformat(), "periodEnd": (monday + timedelta(days=6)).isoformat(),
            "scoringVersion": "balanced-v1", "players": league_period(conn, monday.isoformat(), game_date, tz),
            "previousWinners": [player for player in previous if player["rank"] == 1],
            "previousPeriodEnd": (monday - timedelta(days=1)).isoformat()}

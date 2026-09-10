"""Read-only daily hub and balanced league projections. Original scores never change."""
from datetime import date, datetime, time, timedelta, timezone
import json
import daily_quiz


def today_payload(conn, user_id, game_date, tz=timezone.utc):
    wordle = conn.execute(
        "SELECT r.status, r.attempts_used, r.score FROM wordle_results r "
        "JOIN daily_wordle_games g ON g.id = r.game_id WHERE r.user_id = ? AND g.game_date = ?",
        (user_id, game_date),
    ).fetchone()
    activities = [{"id": "wordle", "title": "Wordle", "href": "/wordle",
                   "status": ("completed" if wordle["status"] != "in_progress" else "continue") if wordle else "ready",
                   "score": wordle["score"] if wordle else None}]
    try:
        available = bool(daily_quiz.quiz_payload(conn, game_date)["questions"])
    except (LookupError, ValueError):
        available = False
    for category, title in (("football", "Football quiz"), ("general", "General knowledge")):
        result = conn.execute(
            "SELECT score FROM daily_quiz_results WHERE user_id = ? AND game_date = ? AND category = ?",
            (user_id, game_date, category),
        ).fetchone()
        progress = conn.execute(
            "SELECT answers_json FROM daily_quiz_progress WHERE user_id = ? AND game_date = ? AND category = ?",
            (user_id, game_date, category),
        ).fetchone()
        activities.append({"id": category, "title": title, "href": f"/quiz?category={category}",
                           "status": "completed" if result else "continue" if progress and json.loads(progress[0]) else "ready" if available else "unavailable",
                           "score": result["score"] if result else None})
    levels = conn.execute(
        "SELECT l.id, g.score, p.revealed_hint_count FROM daily_map_levels l "
        "JOIN daily_map_puzzles d ON d.id = l.puzzle_id "
        "LEFT JOIN daily_map_guesses g ON g.level_id = l.id AND g.user_id = ? "
        "LEFT JOIN daily_map_progress p ON p.level_id = l.id AND p.user_id = ? "
        "WHERE d.puzzle_date = ? AND d.status = 'published'", (user_id, user_id, game_date),
    ).fetchall()
    complete = bool(levels) and all(row["score"] is not None for row in levels)
    activities.append({"id": "map", "title": "Pin the place", "href": "/map",
                       "status": "completed" if complete else "continue" if any(row["revealed_hint_count"] or row["score"] is not None for row in levels) else "ready" if levels else "unavailable",
                       "score": sum(row["score"] or 0 for row in levels) if complete else None})
    tomorrow = date.fromisoformat(game_date) + timedelta(days=1)
    return {"date": game_date, "nextRoundAt": datetime.combine(tomorrow, time(), tz).isoformat(),
            "activities": activities}


def league_period(conn, start, end):
    # Work in hundredths of a point to avoid floating-point tie differences.
    players = {row["id"]: {"id": row["id"], "username": row["username"],
               "games": {key: 0 for key in ("wordle", "football", "general", "map")}}
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
        add(row["user_id"], row["category"], min(1000, max(0, round(row["score"] * 1000 / row["max_score"]))) if row["max_score"] else 0)
    for row in conn.execute(
        "SELECT g.user_id, p.puzzle_date, SUM(g.score) AS score FROM daily_map_guesses g "
        "JOIN daily_map_levels l ON l.id = g.level_id JOIN daily_map_puzzles p ON p.id = l.puzzle_id "
        "WHERE p.puzzle_date BETWEEN ? AND ? GROUP BY g.user_id, p.puzzle_date", (start, end)
    ):
        add(row["user_id"], "map", min(1000, max(0, row["score"] * 100)))
    ordered = sorted(players.values(), key=lambda player: (-sum(player["games"].values()), player["username"].casefold()))
    last_score, rank = None, 0
    for index, player in enumerate(ordered):
        units = sum(player["games"].values())
        if units != last_score:
            rank = index + 1
        last_score = units
        player.update(rank=rank if units else None, points=units / 100)
        player["games"] = {key: value / 100 for key, value in player["games"].items()}
    return ordered


def league_payload(conn, game_date):
    today = date.fromisoformat(game_date)
    monday = today - timedelta(days=today.weekday())
    previous = league_period(conn, (monday - timedelta(days=7)).isoformat(), (monday - timedelta(days=1)).isoformat())
    return {"periodStart": monday.isoformat(), "periodEnd": (monday + timedelta(days=6)).isoformat(),
            "scoringVersion": "balanced-v1", "players": league_period(conn, monday.isoformat(), game_date),
            "previousWinners": [player for player in previous if player["rank"] == 1],
            "previousPeriodEnd": (monday - timedelta(days=1)).isoformat()}

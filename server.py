from __future__ import annotations

import base64
import hashlib
import html
import hmac
import json
import os
import queue
import re
import secrets
import sqlite3
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 fallback
    ZoneInfo = None  # type: ignore[assignment]

APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "fultons.db"
DIST_DIR = APP_DIR / "dist"
QUIZ_DATA_DIR = DATA_DIR / "quizzes"
SESSION_COOKIE = "fultons_session"
SESSION_DAYS = 14
PASSWORD_ITERATIONS = 260_000
USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
SERVER_TZ_NAME = os.environ.get("FULTONS_TIMEZONE", "Europe/London")
NEWS_MONITOR_KEY = os.environ.get("FULTONS_NEWS_MONITOR_KEY", "")
NEWS_LIMIT_DEFAULT = 50
NEWS_LIMIT_MAX = 100
NEWS_MONITOR_ENABLED = os.environ.get("FULTONS_NEWS_MONITOR_ENABLED", "1") != "0"
NEWS_MONITOR_INTERVAL_SEC = max(
    300,
    int(os.environ.get("FULTONS_NEWS_MONITOR_INTERVAL_SEC", "900")),
)
NEWS_USER_AGENT = os.environ.get(
    "FULTONS_NEWS_USER_AGENT",
    "FultonsQuiz/0.1 (+https://fultons-quiz.co.uk)",
)
HISTORY_USER_AGENT = os.environ.get(
    "UPSTREAM_USER_AGENT",
    "FultonHistory/1.0 (+https://fultons-quiz.co.uk)",
)
HISTORY_CACHE_TTL_SEC = int(os.environ.get("HISTORY_CACHE_TTL_SEC", "86400"))
QUIZ_OPENAI_API_KEY = (
    os.environ.get("FULTONS_QUIZ_OPENAI_API_KEY")
    or os.environ.get("FULTONS_OPENAI_API_KEY")
    or os.environ.get("OPENAI_API_KEY")
    or ""
)
QUIZ_OPENAI_MODEL = os.environ.get("FULTONS_QUIZ_OPENAI_MODEL", "gpt-4.1-mini")
QUIZ_OPENAI_TIMEOUT_SEC = int(os.environ.get("FULTONS_QUIZ_OPENAI_TIMEOUT_SEC", "30"))
COOKIE_SECURE = os.environ.get("FULTONS_COOKIE_SECURE", "0") == "1"
SEED_DEMO_USERS = os.environ.get("FULTONS_SEED_DEMO_USERS", "0") == "1"
BOOTSTRAP_ADMIN_USERNAME = os.environ.get("FULTONS_BOOTSTRAP_ADMIN_USERNAME", "").strip()
BOOTSTRAP_ADMIN_PASSWORD = os.environ.get("FULTONS_BOOTSTRAP_ADMIN_PASSWORD", "")
MIN_PASSWORD_LENGTH = int(os.environ.get("FULTONS_MIN_PASSWORD_LENGTH", "12"))
LOGIN_MAX_FAILURES = int(
    os.environ.get("FULTONS_LOGIN_MAX_FAILURES", os.environ.get("FULTONS_LOGIN_MAX_ATTEMPTS", "5"))
)
LOGIN_LOCKOUT_SECONDS = int(
    os.environ.get(
        "FULTONS_LOGIN_LOCKOUT_SECONDS",
        os.environ.get("FULTONS_LOGIN_BACKOFF_SECONDS", "300"),
    )
)
CORS_ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.environ.get("FULTONS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
}
DIFFICULTIES = ("easy", "medium", "hard")
QUIZ_POINTS_BY_DIFFICULTY = {"easy": 1, "medium": 3, "hard": 5}
WORDLE_POINTS_BY_ATTEMPT = {1: 10, 2: 5, 3: 4, 4: 3, 5: 2, 6: 1}
NEWS_QUERIES = (
    '"St Mirren"',
    '"St Mirren" football',
    '"St Mirren" transfer',
    '"St Mirren" Scottish Premiership',
    '"St Mirren" live score',
    '"Scottish Premiership" live scores',
)
SUPPORTED_HISTORY_LANGS = {"en", "fr", "de", "es", "it"}
HISTORY_INTEREST_KEYWORDS = (
    "first",
    "founded",
    "opened",
    "launched",
    "discovered",
    "invented",
    "independence",
    "election",
    "president",
    "prime minister",
    "king",
    "queen",
    "record",
    "award",
    "wins",
    "won",
    "world",
    "historic",
    "landmark",
)
HISTORY_SPORT_KEYWORDS = (
    "football",
    "soccer",
    "cup",
    "league",
    "olympic",
    "olympics",
    "championship",
    "tournament",
    "match",
    "goal",
    "scored",
    "rugby",
    "cricket",
    "tennis",
    "golf",
    "boxing",
    "athletics",
    "racing",
    "sport",
)
HISTORY_FAMOUS_BIRTH_KEYWORDS = (
    "actor",
    "actress",
    "singer",
    "musician",
    "footballer",
    "player",
    "athlete",
    "boxer",
    "golfer",
    "tennis",
    "writer",
    "author",
    "poet",
    "artist",
    "scientist",
    "inventor",
    "politician",
    "president",
    "prime minister",
    "king",
    "queen",
    "director",
    "comedian",
    "journalist",
    "broadcaster",
)
PLACE_ALIASES = {
    "paisley": "Paisley, Renfrewshire",
    "paisley, scotland": "Paisley, Renfrewshire",
    "paisley, renfrewshire": "Paisley, Renfrewshire",
}
PLACE_CANDIDATE_POSITIVE_KEYWORDS = (
    "town",
    "city",
    "village",
    "settlement",
    "burgh",
    "suburb",
    "municipality",
    "locality",
    "council area",
    "renfrewshire",
    "scotland",
    "england",
    "wales",
    "ireland",
)
PLACE_CANDIDATE_NEGATIVE_KEYWORDS = (
    "pattern",
    "design",
    "fabric",
    "surname",
    "album",
    "song",
    "film",
    "novel",
    "company",
    "school",
    "ship",
    "disambiguation",
)
FACT_THEME_KEYWORDS = {
    "history": (
        "abbey",
        "founded",
        "historic",
        "history",
        "century",
        "medieval",
        "royal",
        "war",
        "built",
        "opened",
    ),
    "landmark": (
        "abbey",
        "church",
        "cathedral",
        "castle",
        "museum",
        "park",
        "hall",
        "memorial",
        "station",
        "theatre",
        "landmark",
    ),
    "industry": (
        "industry",
        "industrial",
        "weaving",
        "woven",
        "textile",
        "mill",
        "mills",
        "manufacturing",
        "shipbuilding",
        "pattern",
    ),
    "culture": (
        "festival",
        "culture",
        "cultural",
        "music",
        "art",
        "arts",
        "theatre",
        "museum",
        "event",
        "events",
    ),
    "people": (
        "born",
        "writer",
        "poet",
        "artist",
        "actor",
        "singer",
        "footballer",
        "politician",
        "notable",
        "people",
    ),
    "date": (
        "anniversary",
        "annual",
        "today",
        "date",
        "commemorated",
    ),
}
FACT_THEME_LABELS = {
    "history": "History",
    "landmark": "Landmark",
    "industry": "Industry",
    "culture": "Culture",
    "people": "People",
    "date": "Anniversary",
    "general": "Local fact",
}

NEWS_STREAMS: set[queue.Queue[dict[str, Any]]] = set()
NEWS_STREAMS_LOCK = threading.Lock()
HISTORY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
LOGIN_ATTEMPTS: dict[str, tuple[int, float]] = {}
LOGIN_ATTEMPTS_LOCK = threading.Lock()

sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(APP_DIR))

from wordle_game import (  # noqa: E402
    MAX_ATTEMPTS,
    WORD_LENGTH,
    choose_secret,
    compute_feedback,
    load_word_list,
    reset_used_words,
    serialize_feedback,
    valid_guess,
)


def get_server_timezone() -> timezone:
    if ZoneInfo is None:
        return timezone.utc

    try:
        return ZoneInfo(SERVER_TZ_NAME)  # type: ignore[return-value]
    except Exception:
        return timezone.utc


SERVER_TZ = get_server_timezone()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today_game_date() -> str:
    return datetime.now(SERVER_TZ).date().isoformat()


def safe_log(message: str) -> None:
    try:
        print(message, flush=True)
    except OSError:
        pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return "$".join(
        [
            "pbkdf2_sha256",
            str(PASSWORD_ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False

        salt = base64.b64decode(salt_b64)
        expected_digest = base64.b64decode(digest_b64)
        actual_digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
        return hmac.compare_digest(actual_digest, expected_digest)
    except Exception:
        return False


def validate_username(username: str) -> str | None:
    if not USERNAME_RE.fullmatch(username):
        return "Use 3-32 letters, numbers, underscores, or hyphens."
    return None


def validate_password(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    return None


def connect_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database() -> None:
    with closing(connect_db()) as conn:
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_lower
            ON users (LOWER(username));

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS daily_wordle_games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_date TEXT NOT NULL UNIQUE,
                secret_word TEXT NOT NULL,
                cycle INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS wordle_used_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT NOT NULL,
                game_id INTEGER NOT NULL,
                used_on TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (game_id) REFERENCES daily_wordle_games(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS wordle_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                game_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'in_progress'
                    CHECK (status IN ('in_progress', 'won', 'lost')),
                attempts_used INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (game_id) REFERENCES daily_wordle_games(id) ON DELETE CASCADE,
                UNIQUE (user_id, game_id)
            );

            CREATE TABLE IF NOT EXISTS wordle_guesses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                result_id INTEGER NOT NULL,
                attempt_number INTEGER NOT NULL,
                guess TEXT NOT NULL,
                feedback_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (result_id) REFERENCES wordle_results(id) ON DELETE CASCADE,
                UNIQUE (result_id, attempt_number)
            );

            CREATE TABLE IF NOT EXISTS daily_quiz_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                game_date TEXT NOT NULL,
                category TEXT NOT NULL CHECK (category IN ('football', 'general')),
                answers_json TEXT NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                max_score INTEGER NOT NULL DEFAULT 0,
                correct_count INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE (user_id, game_date, category)
            );

            CREATE TABLE IF NOT EXISTS news_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_key TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL DEFAULT 'article',
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                source TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL,
                host TEXT NOT NULL DEFAULT '',
                priority TEXT NOT NULL DEFAULT 'media',
                tags_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_news_items_published_at
            ON news_items (published_at DESC);
            """
            )
            ensure_column(conn, "users", "is_moderator", "INTEGER NOT NULL DEFAULT 0")
            ensure_column(conn, "daily_wordle_games", "cycle", "INTEGER NOT NULL DEFAULT 1")
            ensure_column(conn, "wordle_results", "score", "INTEGER NOT NULL DEFAULT 0")
            backfill_wordle_scores(conn)
            user_count = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
            if user_count == 0:
                bootstrap_error = validate_bootstrap_admin()
                if bootstrap_error is None and BOOTSTRAP_ADMIN_USERNAME and BOOTSTRAP_ADMIN_PASSWORD:
                    seed_user(conn, BOOTSTRAP_ADMIN_USERNAME, BOOTSTRAP_ADMIN_PASSWORD, "admin")
                    safe_log(f"Bootstrapped admin user {BOOTSTRAP_ADMIN_USERNAME!r}")
                elif SEED_DEMO_USERS:
                    seed_user(conn, "admin", "adminadmin123", "admin")
                    seed_user(conn, "user1", "user1user1234", "user")
                    seed_user(conn, "user2", "user2user1234", "user")
                    safe_log("Seeded demo users because FULTONS_SEED_DEMO_USERS=1")
                else:
                    if bootstrap_error is not None:
                        safe_log(f"Admin bootstrap skipped: {bootstrap_error}")
                    safe_log("No users exist and demo seeding is disabled.")
            backfill_news_categories(conn)


def ensure_column(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})")
    }
    if column_name in columns:
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def seed_user(conn: sqlite3.Connection, username: str, password: str, role: str) -> None:
    row = conn.execute(
        "SELECT id FROM users WHERE LOWER(username) = LOWER(?)",
        (username,),
    ).fetchone()
    if row is not None:
        return

    now = utc_now()
    conn.execute(
        """
        INSERT INTO users (username, password_hash, role, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (username, hash_password(password), role, now, now),
    )


def validate_bootstrap_admin() -> str | None:
    if not BOOTSTRAP_ADMIN_USERNAME and not BOOTSTRAP_ADMIN_PASSWORD:
        return None
    if not BOOTSTRAP_ADMIN_USERNAME or not BOOTSTRAP_ADMIN_PASSWORD:
        return "set both FULTONS_BOOTSTRAP_ADMIN_USERNAME and FULTONS_BOOTSTRAP_ADMIN_PASSWORD"

    username_error = validate_username(BOOTSTRAP_ADMIN_USERNAME)
    if username_error is not None:
        return f"bootstrap username invalid: {username_error}"

    password_error = validate_password(BOOTSTRAP_ADMIN_PASSWORD)
    if password_error is not None:
        return f"bootstrap password invalid: {password_error}"

    return None


def row_has_value(row: sqlite3.Row, key: str) -> bool:
    return key in row.keys() and bool(row[key])


def effective_user_role(row: sqlite3.Row) -> str:
    if row["role"] == "admin":
        return "admin"
    return "mod" if row_has_value(row, "is_moderator") else "user"


def user_can_manage_players(row: sqlite3.Row) -> bool:
    return row["role"] == "admin" or row_has_value(row, "is_moderator")


def user_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "username": row["username"], "role": effective_user_role(row)}


def admin_user_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": effective_user_role(row),
        "createdAt": row["created_at"],
        "gamesPlayed": row["games_played"] or 0,
        "wins": row["wins"] or 0,
        "losses": row["losses"] or 0,
    }


def create_session(conn: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    expires_at = now + timedelta(days=SESSION_DAYS)
    conn.execute(
        """
        INSERT INTO sessions (token, user_id, created_at, expires_at)
        VALUES (?, ?, ?, ?)
        """,
        (token, user_id, now.isoformat(), expires_at.isoformat()),
    )
    return token


def get_cookie_value(headers: Any, name: str) -> str | None:
    raw_cookie = headers.get("Cookie")
    if not raw_cookie:
        return None

    cookie = SimpleCookie()
    cookie.load(raw_cookie)
    morsel = cookie.get(name)
    return morsel.value if morsel is not None else None


def cookie_attributes(max_age: int) -> str:
    attributes = [f"Path=/", "HttpOnly", "SameSite=Lax", f"Max-Age={max_age}"]
    if COOKIE_SECURE:
        attributes.append("Secure")
    return "; ".join(attributes)


def session_header(token: str) -> str:
    max_age = SESSION_DAYS * 24 * 60 * 60
    return f"{SESSION_COOKIE}={token}; {cookie_attributes(max_age)}"


def clear_session_header() -> str:
    return f"{SESSION_COOKIE}=; {cookie_attributes(0)}"


def current_user(conn: sqlite3.Connection, token: str | None) -> sqlite3.Row | None:
    if token is None:
        return None

    now = utc_now()
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
    return conn.execute(
        """
        SELECT users.*
        FROM sessions
        JOIN users ON users.id = sessions.user_id
        WHERE sessions.token = ? AND sessions.expires_at > ?
        """,
        (token, now),
    ).fetchone()


def login_attempt_key(username: str, client_ip: str) -> str:
    return f"{username.lower()}|{client_ip}"


def is_login_locked(username: str, client_ip: str) -> bool:
    key = login_attempt_key(username, client_ip)
    now = time.time()

    with LOGIN_ATTEMPTS_LOCK:
        attempts = LOGIN_ATTEMPTS.get(key)
        if attempts is None:
            return False

        failure_count, locked_until = attempts
        if locked_until > 0 and locked_until <= now:
            LOGIN_ATTEMPTS.pop(key, None)
            return False

        return locked_until > now and failure_count >= LOGIN_MAX_FAILURES


def record_login_failure(username: str, client_ip: str) -> None:
    key = login_attempt_key(username, client_ip)
    now = time.time()

    with LOGIN_ATTEMPTS_LOCK:
        failure_count, locked_until = LOGIN_ATTEMPTS.get(key, (0, 0.0))
        if locked_until > 0 and locked_until <= now:
            failure_count = 0
        failure_count += 1
        next_locked_until = (
            now + LOGIN_LOCKOUT_SECONDS if failure_count >= LOGIN_MAX_FAILURES else locked_until
        )
        LOGIN_ATTEMPTS[key] = (failure_count, next_locked_until)


def clear_login_failures(username: str, client_ip: str) -> None:
    with LOGIN_ATTEMPTS_LOCK:
        LOGIN_ATTEMPTS.pop(login_attempt_key(username, client_ip), None)


def ensure_daily_game(conn: sqlite3.Connection) -> sqlite3.Row:
    game_date = today_game_date()
    game = conn.execute(
        "SELECT * FROM daily_wordle_games WHERE game_date = ?",
        (game_date,),
    ).fetchone()
    if game is not None:
        return game

    words = load_word_list()
    cycle = conn.execute(
        "SELECT COALESCE(MAX(cycle), 1) AS cycle FROM daily_wordle_games"
    ).fetchone()["cycle"]
    used_words = {
        row["secret_word"]
        for row in conn.execute(
            "SELECT secret_word FROM daily_wordle_games WHERE cycle = ?",
            (cycle,),
        )
    }
    if len(used_words) >= len(words):
        cycle += 1
        used_words = set()
        reset_used_words()

    secret_word = choose_secret(words, used_words, include_local_used=False)
    now = utc_now()

    try:
        cursor = conn.execute(
            """
            INSERT INTO daily_wordle_games (game_date, secret_word, cycle, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (game_date, secret_word, cycle, now),
        )
        game_id = cursor.lastrowid
        conn.execute(
            """
            INSERT INTO wordle_used_words (word, game_id, used_on, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (secret_word, game_id, game_date, now),
        )
    except sqlite3.IntegrityError:
        pass

    return conn.execute(
        "SELECT * FROM daily_wordle_games WHERE game_date = ?",
        (game_date,),
    ).fetchone()


def get_or_create_wordle_result(
    conn: sqlite3.Connection,
    user_id: int,
    game_id: int,
) -> sqlite3.Row:
    result = conn.execute(
        """
        SELECT * FROM wordle_results
        WHERE user_id = ? AND game_id = ?
        """,
        (user_id, game_id),
    ).fetchone()
    if result is not None:
        return result

    now = utc_now()
    conn.execute(
        """
        INSERT INTO wordle_results
            (user_id, game_id, status, attempts_used, created_at, updated_at)
        VALUES (?, ?, 'in_progress', 0, ?, ?)
        """,
        (user_id, game_id, now, now),
    )
    return conn.execute(
        """
        SELECT * FROM wordle_results
        WHERE user_id = ? AND game_id = ?
        """,
        (user_id, game_id),
    ).fetchone()


def wordle_score(status: str, attempts_used: int) -> int:
    if status != "won":
        return 0
    return WORDLE_POINTS_BY_ATTEMPT.get(attempts_used, 0)


def backfill_wordle_scores(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, status, attempts_used, score
        FROM wordle_results
        WHERE status != 'in_progress'
        """
    ).fetchall()
    for row in rows:
        next_score = wordle_score(row["status"], row["attempts_used"])
        if row["score"] != next_score:
            conn.execute("UPDATE wordle_results SET score = ? WHERE id = ?", (next_score, row["id"]))


def wordle_stats(conn: sqlite3.Connection, user_id: int) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
            SUM(CASE WHEN status IN ('won', 'lost') THEN 1 ELSE 0 END) AS played,
            SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN status = 'lost' THEN 1 ELSE 0 END) AS losses,
            SUM(score) AS points
        FROM wordle_results
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    return {
        "played": row["played"] or 0,
        "wins": row["wins"] or 0,
        "losses": row["losses"] or 0,
        "points": row["points"] or 0,
    }


def serialize_wordle_state(
    conn: sqlite3.Connection,
    user_id: int,
    game: sqlite3.Row,
) -> dict[str, Any]:
    result = get_or_create_wordle_result(conn, user_id, game["id"])
    guesses = [
        {
            "attemptNumber": row["attempt_number"],
            "guess": row["guess"],
            "feedback": json.loads(row["feedback_json"]),
        }
        for row in conn.execute(
            """
            SELECT attempt_number, guess, feedback_json
            FROM wordle_guesses
            WHERE result_id = ?
            ORDER BY attempt_number
            """,
            (result["id"],),
        )
    ]
    status = result["status"]

    return {
        "game": {
            "date": game["game_date"],
            "wordLength": WORD_LENGTH,
            "maxAttempts": MAX_ATTEMPTS,
        },
        "result": {
            "status": status,
            "attemptsUsed": result["attempts_used"],
            "score": result["score"],
            "guesses": guesses,
            "answer": game["secret_word"] if status != "in_progress" else None,
        },
        "stats": wordle_stats(conn, user_id),
    }


CURATED_QUIZ_BANK: dict[str, dict[str, list[dict[str, Any]]]] = {
    "football": {
        "easy": [
            {
                "question": "What nickname is commonly used for St Mirren?",
                "answers": ["The Buddies", "The Jags", "The Spiders", "The Bairns"],
                "correct_answer": "The Buddies",
                "explanation": "St Mirren are widely known as The Buddies.",
            },
            {
                "question": "In which town is St Mirren Park located?",
                "answers": ["Paisley", "Greenock", "Ayr", "Dumfries"],
                "correct_answer": "Paisley",
                "explanation": "St Mirren Park is in Paisley, Renfrewshire.",
            },
            {
                "question": "How many players does a football team start with on the pitch?",
                "answers": ["9", "10", "11", "12"],
                "correct_answer": "11",
                "explanation": "A standard football team starts with 11 players.",
            },
            {
                "question": "Which card sends a player off in football?",
                "answers": ["Blue", "Green", "Yellow", "Red"],
                "correct_answer": "Red",
                "explanation": "A red card means the player is sent off.",
            },
            {
                "question": "What is the top division of Scottish league football called?",
                "answers": ["Scottish Premiership", "Scottish Championship", "League One", "League Two"],
                "correct_answer": "Scottish Premiership",
                "explanation": "The Scottish Premiership is the top tier of the SPFL.",
            },
        ],
        "medium": [
            {
                "question": "Which year did St Mirren win the Scottish Cup by beating Dundee United 1-0?",
                "answers": ["1977", "1987", "1997", "2007"],
                "correct_answer": "1987",
                "explanation": "St Mirren won the 1987 Scottish Cup final 1-0 at Hampden.",
            },
            {
                "question": "Which club plays its home matches at Tynecastle Park?",
                "answers": ["Hearts", "Hibernian", "Dundee", "Kilmarnock"],
                "correct_answer": "Hearts",
                "explanation": "Tynecastle Park is the home ground of Heart of Midlothian.",
            },
            {
                "question": "What does VAR stand for in football?",
                "answers": [
                    "Video Assistant Referee",
                    "Verified Action Replay",
                    "Virtual Assistant Review",
                    "Video Assessment Rule",
                ],
                "correct_answer": "Video Assistant Referee",
                "explanation": "VAR means Video Assistant Referee.",
            },
            {
                "question": "Which national team did Kenny Dalglish represent?",
                "answers": ["Scotland", "England", "Wales", "Northern Ireland"],
                "correct_answer": "Scotland",
                "explanation": "Kenny Dalglish is one of Scotland's most celebrated footballers.",
            },
            {
                "question": "Which Edinburgh club plays at Easter Road?",
                "answers": ["Hibernian", "Hearts", "Livingston", "Raith Rovers"],
                "correct_answer": "Hibernian",
                "explanation": "Easter Road is Hibernian's home stadium.",
            },
        ],
        "hard": [
            {
                "question": "Who managed St Mirren when they won the 1987 Scottish Cup?",
                "answers": ["Alex Smith", "Tom Hendrie", "Jim Clunie", "Tony Fitzpatrick"],
                "correct_answer": "Alex Smith",
                "explanation": "Alex Smith was St Mirren manager for the 1987 Scottish Cup win.",
            },
            {
                "question": "Who scored St Mirren's winning goal in the 1987 Scottish Cup final?",
                "answers": ["Ian Ferguson", "Frank McGarvey", "Billy Stark", "Neil Cooper"],
                "correct_answer": "Ian Ferguson",
                "explanation": "Ian Ferguson scored the only goal against Dundee United.",
            },
            {
                "question": "Which club did St Mirren beat in the 2013 Scottish League Cup final?",
                "answers": ["Hearts", "Celtic", "Rangers", "Aberdeen"],
                "correct_answer": "Hearts",
                "explanation": "St Mirren beat Hearts 3-2 in the 2013 final.",
            },
            {
                "question": "Which stadium hosted St Mirren's 1987 Scottish Cup final win?",
                "answers": ["Hampden Park", "Ibrox", "Celtic Park", "Pittodrie"],
                "correct_answer": "Hampden Park",
                "explanation": "The 1987 Scottish Cup final was played at Hampden Park.",
            },
            {
                "question": "Which Scottish club is nicknamed The Jambos?",
                "answers": ["Hearts", "Partick Thistle", "Queen's Park", "Falkirk"],
                "correct_answer": "Hearts",
                "explanation": "The Jambos is a common nickname for Heart of Midlothian.",
            },
        ],
    },
    "general": {
        "easy": [
            {
                "question": "Which planet is known as the Red Planet?",
                "answers": ["Mars", "Venus", "Saturn", "Mercury"],
                "correct_answer": "Mars",
                "explanation": "Mars is called the Red Planet because iron oxide gives it a reddish colour.",
            },
            {
                "question": "What is the largest planet in our solar system?",
                "answers": ["Jupiter", "Earth", "Neptune", "Uranus"],
                "correct_answer": "Jupiter",
                "explanation": "Jupiter is the largest planet in the solar system.",
            },
            {
                "question": "At sea level, what temperature does water freeze at in Celsius?",
                "answers": ["0", "10", "32", "100"],
                "correct_answer": "0",
                "explanation": "Water freezes at 0 degrees Celsius at standard pressure.",
            },
            {
                "question": "Who wrote the Harry Potter book series?",
                "answers": ["J.K. Rowling", "Roald Dahl", "Suzanne Collins", "Philip Pullman"],
                "correct_answer": "J.K. Rowling",
                "explanation": "J.K. Rowling wrote the Harry Potter novels.",
            },
            {
                "question": "What is the smallest prime number?",
                "answers": ["1", "2", "3", "5"],
                "correct_answer": "2",
                "explanation": "Two is the smallest prime number and the only even prime.",
            },
        ],
        "medium": [
            {
                "question": "Which Japanese art form is based on folding paper?",
                "answers": ["Origami", "Ikebana", "Haiku", "Bonsai"],
                "correct_answer": "Origami",
                "explanation": "Origami is the art of paper folding.",
            },
            {
                "question": "Who painted The Starry Night?",
                "answers": ["Vincent van Gogh", "Claude Monet", "Pablo Picasso", "Henri Matisse"],
                "correct_answer": "Vincent van Gogh",
                "explanation": "Vincent van Gogh painted The Starry Night in 1889.",
            },
            {
                "question": "What is the currency of Japan?",
                "answers": ["Yen", "Won", "Yuan", "Ringgit"],
                "correct_answer": "Yen",
                "explanation": "Japan's currency is the yen.",
            },
            {
                "question": "What process do plants use to convert light into chemical energy?",
                "answers": ["Photosynthesis", "Respiration", "Fermentation", "Condensation"],
                "correct_answer": "Photosynthesis",
                "explanation": "Photosynthesis lets plants use light to make sugars.",
            },
            {
                "question": "Which organ pumps blood around the human body?",
                "answers": ["Heart", "Liver", "Kidney", "Lung"],
                "correct_answer": "Heart",
                "explanation": "The heart pumps blood through the circulatory system.",
            },
        ],
        "hard": [
            {
                "question": "Which machine is Ada Lovelace most closely associated with?",
                "answers": ["Analytical Engine", "Difference Printer", "Enigma Machine", "Manchester Baby"],
                "correct_answer": "Analytical Engine",
                "explanation": "Ada Lovelace wrote notes about Charles Babbage's Analytical Engine.",
            },
            {
                "question": "Which element has the chemical symbol W?",
                "answers": ["Tungsten", "Tin", "Titanium", "Tellurium"],
                "correct_answer": "Tungsten",
                "explanation": "W comes from wolfram, another name historically used for tungsten.",
            },
            {
                "question": "Which treaty formally ended World War I between Germany and the Allied powers?",
                "answers": ["Treaty of Versailles", "Treaty of Paris", "Treaty of Utrecht", "Treaty of Lisbon"],
                "correct_answer": "Treaty of Versailles",
                "explanation": "The Treaty of Versailles was signed in 1919.",
            },
            {
                "question": "Which modern city was historically known as Constantinople?",
                "answers": ["Istanbul", "Athens", "Sofia", "Ankara"],
                "correct_answer": "Istanbul",
                "explanation": "Constantinople is now Istanbul in Turkiye.",
            },
            {
                "question": "What is the name of the boundary around a black hole beyond which light cannot escape?",
                "answers": ["Event horizon", "Photon belt", "Gravity wall", "Dark limit"],
                "correct_answer": "Event horizon",
                "explanation": "The event horizon marks the point from which nothing can escape a black hole.",
            },
        ],
    },
}

LEGACY_PLACEHOLDER_QUESTION_TEXTS = {
    "Which club plays its home matches at Anfield?",
    "Which nation won UEFA Euro 2016?",
    "Who scored the winning goal for Manchester United in the 1999 UEFA Champions League final?",
    "What is the capital city of France?",
    "Which element has the chemical symbol Au?",
    "In which year was the first successful human heart transplant performed?",
}


def curated_question_for(game_date: str, category: str, difficulty: str) -> dict[str, Any]:
    pool = CURATED_QUIZ_BANK[category][difficulty]
    digest = hashlib.sha256(f"{game_date}:{category}:{difficulty}".encode("utf-8")).digest()
    index = int.from_bytes(digest[:4], "big") % len(pool)
    question = dict(pool[index])
    question["difficulty"] = difficulty
    return question


def curated_daily_questions(game_date: str) -> dict[str, Any]:
    return {
        "date": game_date,
        "football": [
            curated_question_for(game_date, "football", difficulty)
            for difficulty in DIFFICULTIES
        ],
        "general": [
            curated_question_for(game_date, "general", difficulty)
            for difficulty in DIFFICULTIES
        ],
    }


def quiz_json_schema() -> dict[str, Any]:
    question_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["difficulty", "question", "answers", "correct_answer", "explanation"],
        "properties": {
            "difficulty": {"type": "string", "enum": list(DIFFICULTIES)},
            "question": {"type": "string"},
            "answers": {
                "type": "array",
                "minItems": 4,
                "maxItems": 4,
                "items": {"type": "string"},
            },
            "correct_answer": {"type": "string"},
            "explanation": {"type": "string"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["date", "football", "general"],
        "properties": {
            "date": {"type": "string"},
            "football": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": question_schema,
            },
            "general": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": question_schema,
            },
        },
    }


def quiz_generation_prompt(game_date: str) -> str:
    return (
        "Create a Fulton Web App daily quiz payload for date "
        f"{game_date}. Return exactly three football questions and exactly "
        "three general knowledge questions. Each category must include one "
        "easy, one medium, and one hard question. Football should favour St "
        "Mirren, Scottish football, football rules, and memorable football "
        "history. General knowledge should mix science, arts, geography, "
        "language, history, and culture. Avoid obvious sample prompts such as "
        "Anfield, Euro 2016, capital of France, chemical symbol Au, and the "
        "first heart transplant. Use four plausible answer options per "
        "question, keep the correct answer exactly equal to one option, and "
        "write a short explanation."
    )


def extract_openai_response_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    output_items = payload.get("output")
    if not isinstance(output_items, list):
        return ""

    for item in output_items:
        if not isinstance(item, dict):
            continue
        content_items = item.get("content")
        if not isinstance(content_items, list):
            continue
        for content in content_items:
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return text
    return ""


def openai_daily_questions(game_date: str) -> dict[str, Any] | None:
    if not QUIZ_OPENAI_API_KEY:
        return None

    request_payload = {
        "model": QUIZ_OPENAI_MODEL,
        "input": quiz_generation_prompt(game_date),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "fulton_daily_quiz",
                "strict": True,
                "schema": quiz_json_schema(),
            }
        },
    }
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {QUIZ_OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=QUIZ_OPENAI_TIMEOUT_SEC) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as error:
        safe_log(f"OpenAI quiz generation failed; using curated fallback: {error}")
        return None

    response_text = extract_openai_response_text(response_payload)
    if not response_text:
        safe_log("OpenAI quiz generation returned no text; using curated fallback")
        return None

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        safe_log("OpenAI quiz generation returned invalid JSON; using curated fallback")
        return None

    if isinstance(payload, dict):
        payload["date"] = game_date
        if validate_daily_questions(payload):
            return payload

    safe_log("OpenAI quiz generation failed validation; using curated fallback")
    return None


def generated_daily_questions(game_date: str) -> dict[str, Any]:
    return openai_daily_questions(game_date) or curated_daily_questions(game_date)


def contains_legacy_placeholder_questions(payload: dict[str, Any]) -> bool:
    question_texts = {
        question.get("question")
        for category in ("football", "general")
        for question in payload.get(category, [])
        if isinstance(question, dict)
    }
    return LEGACY_PLACEHOLDER_QUESTION_TEXTS.issubset(question_texts)


def validate_daily_questions(payload: dict[str, Any]) -> bool:
    if not isinstance(payload.get("date"), str):
        return False

    for category in ("football", "general"):
        questions = payload.get(category)
        if not isinstance(questions, list) or len(questions) != 3:
            return False

        seen_difficulties = set()
        for question in questions:
            if not isinstance(question, dict):
                return False
            difficulty = question.get("difficulty")
            if difficulty not in DIFFICULTIES:
                return False
            seen_difficulties.add(difficulty)
            answers = question.get("answers")
            correct_answer = question.get("correct_answer")
            if not isinstance(question.get("question"), str) or not question["question"].strip():
                return False
            if not isinstance(answers, list) or len(answers) != 4:
                return False
            if not all(isinstance(answer, str) and answer.strip() for answer in answers):
                return False
            if correct_answer not in answers:
                return False
            if not isinstance(question.get("explanation"), str):
                return False
        if seen_difficulties != set(DIFFICULTIES):
            return False

    return True


def order_daily_questions(payload: dict[str, Any]) -> dict[str, Any]:
    ordered = dict(payload)
    difficulty_index = {difficulty: index for index, difficulty in enumerate(DIFFICULTIES)}
    for category in ("football", "general"):
        questions = payload.get(category)
        if isinstance(questions, list):
            ordered[category] = sorted(
                questions,
                key=lambda question: difficulty_index.get(
                    question.get("difficulty") if isinstance(question, dict) else "",
                    len(DIFFICULTIES),
                ),
            )
    return ordered


def daily_questions_path(game_date: str) -> Path:
    return QUIZ_DATA_DIR / f"daily-questions-{game_date}.json"


def ensure_daily_questions() -> dict[str, Any]:
    game_date = today_game_date()
    QUIZ_DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = daily_questions_path(game_date)

    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                isinstance(payload, dict)
                and payload.get("date") == game_date
                and validate_daily_questions(payload)
                and not contains_legacy_placeholder_questions(payload)
            ):
                return order_daily_questions(payload)
        except (OSError, json.JSONDecodeError):
            pass

    payload = generated_daily_questions(game_date)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(path)
    return order_daily_questions(payload)


def score_quiz_answers(
    questions: list[dict[str, Any]],
    answers: list[str],
) -> dict[str, int]:
    score = 0
    max_score = 0
    correct_count = 0
    for index, question in enumerate(questions):
        difficulty = str(question.get("difficulty", ""))
        points = QUIZ_POINTS_BY_DIFFICULTY.get(difficulty, 0)
        max_score += points
        if index < len(answers) and answers[index] == question.get("correct_answer"):
            score += points
            correct_count += 1
    return {"score": score, "maxScore": max_score, "correctCount": correct_count}


def serialize_quiz_result(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "date": row["game_date"],
        "category": row["category"],
        "score": row["score"],
        "maxScore": row["max_score"],
        "correctCount": row["correct_count"],
        "completedAt": row["completed_at"],
    }


def save_daily_quiz_result(
    conn: sqlite3.Connection,
    user_id: int,
    game_date: str,
    category: str,
    answers: list[str],
) -> tuple[dict[str, Any], int]:
    daily_questions = ensure_daily_questions()
    if game_date != daily_questions["date"]:
        return {"error": "Only today's quiz can be scored."}, HTTPStatus.BAD_REQUEST
    if category not in {"football", "general"}:
        return {"error": "Quiz category must be football or general."}, HTTPStatus.BAD_REQUEST

    questions = daily_questions[category]
    if len(answers) != len(questions):
        return {"error": "Submit one answer for each quiz question."}, HTTPStatus.BAD_REQUEST

    existing = conn.execute(
        """
        SELECT *
        FROM daily_quiz_results
        WHERE user_id = ? AND game_date = ? AND category = ?
        """,
        (user_id, game_date, category),
    ).fetchone()
    if existing is not None:
        return {"result": serialize_quiz_result(existing)}, HTTPStatus.OK

    totals = score_quiz_answers(questions, answers)
    now = utc_now()
    try:
        conn.execute(
            """
            INSERT INTO daily_quiz_results (
                user_id, game_date, category, answers_json, score, max_score,
                correct_count, completed_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                game_date,
                category,
                json.dumps(answers),
                totals["score"],
                totals["maxScore"],
                totals["correctCount"],
                now,
                now,
                now,
            ),
        )
    except sqlite3.IntegrityError:
        pass

    result = conn.execute(
        """
        SELECT *
        FROM daily_quiz_results
        WHERE user_id = ? AND game_date = ? AND category = ?
        """,
        (user_id, game_date, category),
    ).fetchone()
    return {"result": serialize_quiz_result(result)}, HTTPStatus.CREATED


def leaderboard_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        WITH wordle_scores AS (
            SELECT
                user_id,
                SUM(score) AS points,
                SUM(CASE WHEN status IN ('won', 'lost') THEN 1 ELSE 0 END) AS played,
                SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END) AS wins
            FROM wordle_results
            GROUP BY user_id
        ),
        quiz_scores AS (
            SELECT
                user_id,
                SUM(score) AS points,
                SUM(max_score) AS max_points,
                COUNT(*) AS played,
                SUM(correct_count) AS correct_count
            FROM daily_quiz_results
            GROUP BY user_id
        )
        SELECT
            users.id,
            users.username,
            COALESCE(wordle_scores.points, 0) AS wordle_points,
            COALESCE(wordle_scores.played, 0) AS wordle_played,
            COALESCE(wordle_scores.wins, 0) AS wordle_wins,
            COALESCE(quiz_scores.points, 0) AS quiz_points,
            COALESCE(quiz_scores.max_points, 0) AS quiz_max_points,
            COALESCE(quiz_scores.played, 0) AS quiz_played,
            COALESCE(quiz_scores.correct_count, 0) AS quiz_correct
        FROM users
        LEFT JOIN wordle_scores ON wordle_scores.user_id = users.id
        LEFT JOIN quiz_scores ON quiz_scores.user_id = users.id
        WHERE users.role != 'admin'
        ORDER BY
            (COALESCE(wordle_scores.points, 0) + COALESCE(quiz_scores.points, 0)) DESC,
            COALESCE(wordle_scores.wins, 0) DESC,
            LOWER(users.username)
        """
    ).fetchall()

    players = []
    for index, row in enumerate(rows):
        players.append(
            {
                "rank": index + 1,
                "id": row["id"],
                "username": row["username"],
                "totalPoints": row["wordle_points"] + row["quiz_points"],
                "wordlePoints": row["wordle_points"],
                "wordlePlayed": row["wordle_played"],
                "wordleWins": row["wordle_wins"],
                "quizPoints": row["quiz_points"],
                "quizMaxPoints": row["quiz_max_points"],
                "quizPlayed": row["quiz_played"],
                "quizCorrect": row["quiz_correct"],
            }
        )

    return {
        "players": players,
        "summary": {
            "playerCount": len(players),
            "totalPoints": sum(player["totalPoints"] for player in players),
            "quizPlays": sum(player["quizPlayed"] for player in players),
            "wordlePlays": sum(player["wordlePlayed"] for player in players),
        },
    }


def serialize_news_item(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sourceKey": row["source_key"],
        "kind": row["kind"],
        "title": row["title"],
        "url": row["url"],
        "source": row["source"],
        "summary": row["summary"],
        "publishedAt": row["published_at"],
        "host": row["host"],
        "priority": row["priority"],
        "tags": json.loads(row["tags_json"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def bounded_text(value: Any, max_length: int) -> str:
    text = str(value or "").strip()
    return text[:max_length]


def validate_news_payload(payload: dict[str, Any]) -> dict[str, Any]:
    source_key = bounded_text(payload.get("sourceKey"), 160)
    title = bounded_text(payload.get("title"), 220)
    url = bounded_text(payload.get("url"), 600)
    source = bounded_text(payload.get("source"), 120) or "Unknown source"
    summary = bounded_text(payload.get("summary"), 500)
    host = bounded_text(payload.get("host"), 160)
    kind = bounded_text(payload.get("kind"), 40) or "article"
    published_at = bounded_text(payload.get("publishedAt"), 80) or utc_now()

    if not source_key:
        source_key = hashlib.sha256(url.encode("utf-8")).hexdigest() if url else ""
    if not source_key:
        raise ValueError("News item requires sourceKey or url.")
    if not title:
        raise ValueError("News item requires title.")
    if not url.startswith(("http://", "https://")):
        raise ValueError("News item requires an http or https url.")

    raw_tags = payload.get("tags", [])
    tags = raw_tags if isinstance(raw_tags, list) else []
    clean_tags = [bounded_text(tag, 40) for tag in tags if bounded_text(tag, 40)]
    priority, clean_tags = classify_news_item(title, summary, clean_tags)

    return {
        "source_key": source_key,
        "kind": kind,
        "title": title,
        "url": url,
        "source": source,
        "summary": summary,
        "published_at": published_at,
        "host": host,
        "priority": priority,
        "tags_json": json.dumps(clean_tags[:8]),
    }


def upsert_news_item(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    item = validate_news_payload(payload)
    now = utc_now()
    existing = conn.execute(
        "SELECT id FROM news_items WHERE source_key = ?",
        (item["source_key"],),
    ).fetchone()

    if existing is None:
        cursor = conn.execute(
            """
            INSERT INTO news_items (
                source_key, kind, title, url, source, summary, published_at,
                host, priority, tags_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["source_key"],
                item["kind"],
                item["title"],
                item["url"],
                item["source"],
                item["summary"],
                item["published_at"],
                item["host"],
                item["priority"],
                item["tags_json"],
                now,
                now,
            ),
        )
        row_id = cursor.lastrowid
        inserted = True
    else:
        row_id = existing["id"]
        conn.execute(
            """
            UPDATE news_items
            SET kind = ?, title = ?, url = ?, source = ?, summary = ?,
                published_at = ?, host = ?, priority = ?, tags_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                item["kind"],
                item["title"],
                item["url"],
                item["source"],
                item["summary"],
                item["published_at"],
                item["host"],
                item["priority"],
                item["tags_json"],
                now,
                row_id,
            ),
        )
        inserted = False

    row = conn.execute("SELECT * FROM news_items WHERE id = ?", (row_id,)).fetchone()
    return serialize_news_item(row), inserted


def list_news_items(
    conn: sqlite3.Connection,
    limit: int,
    category: str = "all",
) -> list[dict[str, Any]]:
    filters = {
        "breaking": "priority = 'breaking'",
        "live-scores": "priority = 'live-scores'",
        "news": "priority = 'news'",
    }
    where_clause = f"WHERE {filters[category]}" if category in filters else ""
    rows = conn.execute(
        f"""
        SELECT *
        FROM news_items
        {where_clause}
        ORDER BY published_at DESC, created_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [serialize_news_item(row) for row in rows]


def broadcast_news_item(item: dict[str, Any]) -> None:
    with NEWS_STREAMS_LOCK:
        streams = list(NEWS_STREAMS)

    for stream in streams:
        try:
            stream.put_nowait(item)
        except queue.Full:
            pass


def contains_news_term(text: str, terms: tuple[str, ...]) -> bool:
    for term in terms:
        pattern = rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])"
        if re.search(pattern, text):
            return True
    return False


def classify_news_item(
    title: str,
    summary: str,
    tags: list[str],
) -> tuple[str, list[str]]:
    haystack = f"{title} {summary}".lower()
    clean_tags = [
        tag
        for tag in list(dict.fromkeys(tags))
        if tag not in {"breaking", "news", "live-scores"}
    ]

    live_score_terms = (
        "live score",
        "livescore",
        "live scores",
        "match centre",
        "match center",
        "fixtures",
        "results",
        "full-time",
        "half-time",
        "kick-off",
    )
    explicit_breaking_terms = (
        "breaking",
        "exclusive",
        "urgent",
        "just in",
        "developing",
    )
    high_impact_breaking_terms = (
        "sacked",
        "dismissed",
        "appointed",
        "resigns",
        "resigned",
        "dies",
        "died",
        "death",
        "postponed",
        "cancelled",
        "called off",
    )

    if contains_news_term(haystack, live_score_terms):
        clean_tags.append("live-scores")
        return "live-scores", list(dict.fromkeys(clean_tags))

    if contains_news_term(haystack, explicit_breaking_terms) or contains_news_term(
        haystack,
        high_impact_breaking_terms,
    ):
        clean_tags.append("breaking")
        return "breaking", list(dict.fromkeys(clean_tags))

    clean_tags.append("news")
    return "news", list(dict.fromkeys(clean_tags))


def backfill_news_categories(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, title, summary, priority, tags_json
        FROM news_items
        """
    ).fetchall()

    for row in rows:
        try:
            tags = json.loads(row["tags_json"])
        except json.JSONDecodeError:
            tags = []
        clean_tags = tags if isinstance(tags, list) else []
        priority, next_tags = classify_news_item(row["title"], row["summary"], clean_tags)
        next_tags_json = json.dumps(next_tags[:8])
        if priority == row["priority"] and next_tags_json == row["tags_json"]:
            continue
        conn.execute(
            """
            UPDATE news_items
            SET priority = ?, tags_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (priority, next_tags_json, utc_now(), row["id"]),
        )


def strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(value))).strip()


def parse_news_datetime(value: str) -> str:
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    except Exception:
        return utc_now()


def google_news_rss_url(query: str) -> str:
    return (
        "https://news.google.com/rss/search"
        f"?q={quote_plus(query)}&hl=en-GB&gl=GB&ceid=GB:en"
    )


def fetch_news_feed(query: str) -> list[dict[str, Any]]:
    request = Request(
        google_news_rss_url(query),
        headers={"User-Agent": NEWS_USER_AGENT},
    )
    with urlopen(request, timeout=10) as response:
        raw_xml = response.read()

    root = ElementTree.fromstring(raw_xml)
    items: list[dict[str, Any]] = []

    for entry in root.findall("./channel/item")[:10]:
        title = strip_html(entry.findtext("title") or "")
        url = (entry.findtext("link") or "").strip()
        summary = strip_html(entry.findtext("description") or "")
        published_at = parse_news_datetime(entry.findtext("pubDate") or "")
        source = strip_html(entry.findtext("source") or "Google News")
        host = urlparse(url).netloc

        if not title or not url.startswith(("http://", "https://")):
            continue

        source_key = hashlib.sha256(f"{title}|{url}".encode("utf-8")).hexdigest()
        items.append(
            {
                "sourceKey": source_key,
                "kind": "article",
                "title": title,
                "url": url,
                "source": source,
                "summary": summary,
                "publishedAt": published_at,
                "host": host,
                "priority": "media",
                "tags": ["st-mirren", "scottish-football"],
            }
        )

    return items


def ingest_news_once() -> int:
    inserted_count = 0
    seen_keys: set[str] = set()

    with connect_db() as conn:
        for query in NEWS_QUERIES:
            try:
                items = fetch_news_feed(query)
            except Exception as error:
                safe_log(f"News monitor fetch failed for {query}: {error}")
                continue

            for payload in items:
                source_key = str(payload.get("sourceKey", ""))
                if source_key in seen_keys:
                    continue
                seen_keys.add(source_key)

                try:
                    item, inserted = upsert_news_item(conn, payload)
                except ValueError as error:
                    safe_log(f"News monitor skipped item: {error}")
                    continue

                if inserted:
                    inserted_count += 1
                    broadcast_news_item(item)

    return inserted_count


def news_monitor_loop() -> None:
    safe_log("News monitor started")

    while True:
        try:
            inserted_count = ingest_news_once()
            if inserted_count:
                safe_log(f"News monitor inserted {inserted_count} item(s)")
        except Exception as error:
            safe_log(f"News monitor error: {error}")
        time.sleep(NEWS_MONITOR_INTERVAL_SEC)


def start_news_monitor() -> None:
    if not NEWS_MONITOR_ENABLED:
        safe_log("News monitor disabled")
        return

    thread = threading.Thread(target=news_monitor_loop, daemon=True)
    thread.start()


def normalise_history_lang(value: str) -> str:
    lang = str(value or "en").lower().split("-")[0]
    return lang if lang in SUPPORTED_HISTORY_LANGS else "en"


def normalise_history_location(value: str) -> str:
    location = unicodedata.normalize("NFC", str(value or "")).strip()
    if len(location) > 120:
        raise ValueError("Location must be 120 characters or fewer.")
    if any(ord(character) < 32 for character in location):
        raise ValueError("Location contains invalid characters.")
    return location


def parse_history_date(value: str) -> tuple[str, int, int] | None:
    raw = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return None

    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None

    return raw, parsed.month, parsed.day


def history_cache_get(key: str) -> dict[str, Any] | None:
    cached = HISTORY_CACHE.get(key)
    if cached is None:
        return None

    stored_at, payload = cached
    if time.time() - stored_at > HISTORY_CACHE_TTL_SEC:
        HISTORY_CACHE.pop(key, None)
        return None

    result = dict(payload)
    result["meta"] = {**payload.get("meta", {}), "cached": True}
    return result


def history_cache_set(key: str, payload: dict[str, Any]) -> None:
    HISTORY_CACHE[key] = (time.time(), payload)


def fetch_json_url(url: str, timeout: int = 8) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": HISTORY_USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def normalise_place_alias_key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def resolve_place_alias(location: str) -> str:
    return PLACE_ALIASES.get(normalise_place_alias_key(location), location)


def wikipedia_summary_url(lang: str, title: str) -> str:
    safe_title = quote_plus(title.replace(" ", "_"), safe=",")
    return f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{safe_title}"


def wikipedia_search_url(lang: str, query: str, limit: int = 8) -> str:
    return (
        f"https://{lang}.wikipedia.org/w/rest.php/v1/search/page"
        f"?q={quote_plus(query)}&limit={limit}"
    )


def wikipedia_plain_extract_url(lang: str, title: str) -> str:
    return (
        f"https://{lang}.wikipedia.org/w/api.php?action=query&format=json"
        f"&prop=extracts&explaintext=1&exlimit=1&redirects=1&titles={quote_plus(title)}"
    )


def wikidata_entity_url(qid: str) -> str:
    return f"https://www.wikidata.org/wiki/Special:EntityData/{quote_plus(qid)}.json"


def wikidata_labels_url(qids: list[str], lang: str) -> str:
    return (
        "https://www.wikidata.org/w/api.php?action=wbgetentities&format=json"
        f"&ids={quote_plus('|'.join(qids), safe='|')}&props=labels&languages={quote_plus(lang)}|en"
    )


def wikipedia_candidate_score(query: str, page: dict[str, Any]) -> int:
    title = strip_html(str(page.get("title", "")))
    description = strip_html(str(page.get("description", "")))
    excerpt = strip_html(str(page.get("excerpt", "")))
    title_lower = title.lower()
    query_lower = normalise_place_alias_key(query)
    combined = f"{title} {description} {excerpt}".lower()
    score = 0

    if title_lower == query_lower:
        score += 20
    if title_lower.startswith(f"{query_lower},"):
        score += 30
    if query_lower and query_lower in title_lower:
        score += 20
    if "," in title:
        score += 8
    score += history_keyword_score(combined, PLACE_CANDIDATE_POSITIVE_KEYWORDS, 18)
    score -= history_keyword_score(combined, PLACE_CANDIDATE_NEGATIVE_KEYWORDS, 40)
    return score


def resolve_wikipedia_place_title(location: str, lang: str) -> str:
    aliased = resolve_place_alias(location)
    if aliased != location:
        return aliased

    try:
        search = fetch_json_url(wikipedia_search_url(lang, location))
    except Exception:
        return location

    pages = search.get("pages")
    if not isinstance(pages, list) or not pages:
        return location

    candidates: list[tuple[int, str]] = []
    for page in pages:
        if not isinstance(page, dict) or not page.get("title"):
            continue
        candidates.append((wikipedia_candidate_score(location, page), str(page["title"])))

    if not candidates:
        return location

    candidates.sort(reverse=True)
    best_score, best_title = candidates[0]
    return best_title if best_score > 0 else location


def fetch_wikipedia_summary(location: str, lang: str) -> dict[str, Any]:
    title = resolve_wikipedia_place_title(location, lang)
    try:
        return fetch_json_url(wikipedia_summary_url(lang, title))
    except Exception:
        search = fetch_json_url(wikipedia_search_url(lang, location, 1))
        pages = search.get("pages")
        if not isinstance(pages, list) or not pages:
            raise LookupError("Location not found.")

        title = pages[0].get("title")
        if not title:
            raise LookupError("Location not found.")
        return fetch_json_url(wikipedia_summary_url(lang, str(title)))


def fetch_wikipedia_plain_extract(title: str, lang: str) -> str:
    payload = fetch_json_url(wikipedia_plain_extract_url(lang, title))
    pages = payload.get("query", {}).get("pages", {}) if isinstance(payload, dict) else {}
    if not isinstance(pages, dict):
        return ""

    for page in pages.values():
        if isinstance(page, dict) and isinstance(page.get("extract"), str):
            return page["extract"]
    return ""


def fetch_wikidata_entity(qid: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"Q\d+", str(qid or "")):
        return None

    payload = fetch_json_url(wikidata_entity_url(qid))
    entity = payload.get("entities", {}).get(qid)
    return entity if isinstance(entity, dict) else None


def fetch_wikidata_labels(qids: list[str], lang: str) -> dict[str, str]:
    clean_qids = sorted({qid for qid in qids if re.fullmatch(r"Q\d+", qid)})
    if not clean_qids:
        return {}

    try:
        payload = fetch_json_url(wikidata_labels_url(clean_qids, lang))
    except Exception:
        return {}

    entities = payload.get("entities", {})
    if not isinstance(entities, dict):
        return {}

    labels: dict[str, str] = {}
    for qid, entity in entities.items():
        if not isinstance(entity, dict):
            continue
        label_map = entity.get("labels", {})
        if not isinstance(label_map, dict):
            continue
        label = label_map.get(lang) or label_map.get("en")
        if isinstance(label, dict) and isinstance(label.get("value"), str):
            labels[str(qid)] = label["value"]
    return labels


def split_fact_sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\[[^\]]+\]", "", str(text or ""))
    cleaned = re.sub(r"\s+", " ", cleaned)
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def clean_fact_sentence(sentence: str) -> str | None:
    cleaned = re.sub(r"=+\s*[^=]+\s*=+", " ", str(sentence or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) < 38 or len(cleaned) > 260:
        return None
    if " may refer to:" in cleaned.lower() or " may refer to " in cleaned.lower():
        return None
    if "according to" in cleaned.lower():
        return None
    if cleaned.count(",") > 8:
        return None
    return cleaned


def fact_keyword_score(text: str, keywords: tuple[str, ...], points: int) -> int:
    score = 0
    for keyword in keywords:
        pattern = rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])"
        if re.search(pattern, text.lower()):
            score += points
    return score


def classify_fact_theme(sentence: str) -> str:
    scored = [
        (fact_keyword_score(sentence, keywords, 1), theme)
        for theme, keywords in FACT_THEME_KEYWORDS.items()
    ]
    scored.sort(reverse=True)
    return scored[0][1] if scored and scored[0][0] > 0 else "general"


def fact_candidate_score(sentence: str, theme: str) -> int:
    score = 0 if theme == "general" else 30
    score += fact_keyword_score(sentence, FACT_THEME_KEYWORDS.get(theme, ()), 5)
    if re.search(r"\b(1[0-9]{3}|20[0-9]{2}|[0-9]{1,2}(st|nd|rd|th) century)\b", sentence):
        score += 12
    if 70 <= len(sentence) <= 190:
        score += 8
    return score


def make_history_fact(
    *,
    title: str,
    text: str,
    theme: str,
    source_name: str,
    source_url: str | None,
    confidence: str,
) -> dict[str, Any]:
    return {
        "title": title,
        "text": text,
        "theme": theme,
        "sourceName": source_name,
        "sourceUrl": source_url,
        "confidence": confidence,
    }


def wikipedia_facts(
    summary: dict[str, Any],
    plain_extract: str,
    limit: int,
    article_url: str | None,
) -> list[dict[str, Any]]:
    candidates: list[tuple[int, dict[str, Any]]] = []
    seen_sentences: set[str] = set()
    source_texts = [
        (str(summary.get("extract", "")), "medium"),
        (plain_extract, "medium"),
    ]

    for text, confidence in source_texts:
        for sentence in split_fact_sentences(text):
            cleaned = clean_fact_sentence(sentence)
            if cleaned is None:
                continue
            sentence_key = re.sub(r"\W+", "", cleaned.lower())[:120]
            if sentence_key in seen_sentences:
                continue
            seen_sentences.add(sentence_key)
            theme = classify_fact_theme(cleaned)
            fact = make_history_fact(
                title=FACT_THEME_LABELS.get(theme, "Local fact"),
                text=cleaned,
                theme=theme,
                source_name="Wikipedia",
                source_url=article_url,
                confidence=confidence,
            )
            candidates.append((fact_candidate_score(cleaned, theme), fact))

    candidates.sort(key=lambda candidate: candidate[0], reverse=True)
    selected: list[dict[str, Any]] = []
    selected_themes: set[str] = set()

    for _, fact in candidates:
        theme = str(fact.get("theme", "general"))
        if theme == "general" or theme in selected_themes:
            continue
        selected.append(fact)
        selected_themes.add(theme)
        if len(selected) >= limit:
            return selected

    for _, fact in candidates:
        if fact in selected:
            continue
        selected.append(fact)
        if len(selected) >= limit:
            break

    return selected


def wikidata_claims(entity: dict[str, Any], property_id: str) -> list[dict[str, Any]]:
    claims = entity.get("claims", {})
    values = claims.get(property_id, []) if isinstance(claims, dict) else []
    return values if isinstance(values, list) else []


def wikidata_claim_value(claim: dict[str, Any]) -> Any:
    mainsnak = claim.get("mainsnak", {}) if isinstance(claim, dict) else {}
    datavalue = mainsnak.get("datavalue", {}) if isinstance(mainsnak, dict) else {}
    return datavalue.get("value") if isinstance(datavalue, dict) else None


def wikidata_time_text(value: Any) -> str | None:
    if not isinstance(value, dict) or not isinstance(value.get("time"), str):
        return None
    match = re.search(r"([+-]\d{4,})-(\d{2})-(\d{2})", value["time"])
    if match is None:
        return None
    year = int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3))
    if month == 1 and day == 1:
        return str(year)
    return f"{year:04d}-{month:02d}-{day:02d}"


def wikidata_quantity_text(value: Any) -> str | None:
    if not isinstance(value, dict) or not isinstance(value.get("amount"), str):
        return None
    try:
        number = float(value["amount"])
    except ValueError:
        return None
    return f"{number:,.0f}" if number.is_integer() else f"{number:,.2f}"


def wikidata_entity_id(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    numeric_id = value.get("numeric-id")
    return f"Q{numeric_id}" if isinstance(numeric_id, int) else None


def wikidata_entity_label(entity: dict[str, Any], lang: str, fallback: str) -> str:
    labels = entity.get("labels", {})
    if isinstance(labels, dict):
        label = labels.get(lang) or labels.get("en")
        if isinstance(label, dict) and isinstance(label.get("value"), str):
            return label["value"]
    return fallback


def wikidata_profile(
    entity: dict[str, Any] | None,
    lang: str,
    fallback_title: str,
) -> dict[str, Any] | None:
    if entity is None:
        return None

    qid = str(entity.get("id", ""))
    source_url = f"https://www.wikidata.org/wiki/{qid}" if qid else None
    title = wikidata_entity_label(entity, lang, fallback_title)
    related_ids: list[str] = []

    for property_id in ("P31", "P131", "P17"):
        for claim in wikidata_claims(entity, property_id)[:3]:
            entity_id = wikidata_entity_id(wikidata_claim_value(claim))
            if entity_id:
                related_ids.append(entity_id)

    related_labels = fetch_wikidata_labels(related_ids, lang)
    instance_labels = [
        related_labels[entity_id]
        for claim in wikidata_claims(entity, "P31")[:3]
        if (entity_id := wikidata_entity_id(wikidata_claim_value(claim))) in related_labels
    ]
    population = None
    for claim in wikidata_claims(entity, "P1082")[:1]:
        population = wikidata_quantity_text(wikidata_claim_value(claim))

    inception = None
    for claim in wikidata_claims(entity, "P571")[:1]:
        inception = wikidata_time_text(wikidata_claim_value(claim))
    containing_places = [
        related_labels[entity_id]
        for claim in wikidata_claims(entity, "P131")[:2]
        if (entity_id := wikidata_entity_id(wikidata_claim_value(claim))) in related_labels
    ]
    countries = [
        related_labels[entity_id]
        for claim in wikidata_claims(entity, "P17")[:1]
        if (entity_id := wikidata_entity_id(wikidata_claim_value(claim))) in related_labels
    ]

    return {
        "title": title,
        "types": instance_labels,
        "population": population,
        "areas": containing_places,
        "country": countries[0] if countries else None,
        "inception": inception,
        "sourceName": "Wikidata",
        "sourceUrl": source_url,
    }


def build_location_facts(
    summary: dict[str, Any],
    plain_extract: str,
    limit: int,
    article_url: str | None,
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    existing_texts: set[str] = set()
    for fact in wikipedia_facts(summary, plain_extract, limit, article_url):
        text = str(fact.get("text", "")).lower()
        if text in existing_texts:
            continue
        facts.append(fact)
        existing_texts.add(text)
        if len(facts) >= limit:
            break

    return facts[:limit]


def history_year_value(value: object) -> int | None:
    raw = str(value or "").strip()
    match = re.search(r"\d+", raw)
    if match is None:
        return None
    year = int(match.group(0))
    return -year if "BC" in raw.upper() or "BCE" in raw.upper() else year


def history_keyword_score(text: str, keywords: tuple[str, ...], points: int) -> int:
    text_lower = text.lower()
    return sum(points for keyword in keywords if keyword in text_lower)


def history_recency_score(year: int | None) -> int:
    if year is None:
        return 0
    if year < 0:
        return -20

    current_year = datetime.now(timezone.utc).year
    age = current_year - year
    if age < 0:
        return 0
    if age <= 40:
        return 60
    if age <= 100:
        return 48
    if age <= 180:
        return 34
    if age <= 300:
        return 22
    if age <= 500:
        return 10
    return 0


def normalise_history_item(item: object, category: str) -> dict[str, Any] | None:
    if not isinstance(item, dict) or not item.get("text"):
        return None

    return {
        "year": str(item.get("year", "")),
        "text": str(item.get("text", "")),
        "links": item.get("links", []) if isinstance(item.get("links"), list) else [],
        "category": category,
    }


def ranked_history_items(items: list[dict[str, Any]], category: str) -> list[dict[str, Any]]:
    scored: list[tuple[int, int, dict[str, Any]]] = []

    for item in items:
        text = str(item.get("text", ""))
        year = history_year_value(item.get("year"))
        score = history_recency_score(year)

        if category == "sport":
            score += history_keyword_score(text, HISTORY_SPORT_KEYWORDS, 24)
        elif category == "born":
            score += history_keyword_score(text, HISTORY_FAMOUS_BIRTH_KEYWORDS, 18)
        else:
            score += history_keyword_score(text, HISTORY_INTEREST_KEYWORDS, 12)

        scored.append((score, year if year is not None else -9999, item))

    scored.sort(key=lambda candidate: (candidate[0], candidate[1]), reverse=True)
    return [item for _, _, item in scored]


def fetch_history_events(month: int, day: int, limit: int) -> list[dict[str, Any]]:
    payload = fetch_json_url(f"https://history.muffinlabs.com/date/{month}/{day}")
    data = payload.get("data", {})
    events = data.get("Events", []) if isinstance(data, dict) else []
    births = data.get("Births", []) if isinstance(data, dict) else []
    if not isinstance(events, list):
        return []

    normalised_events = [
        normalised
        for item in events
        if (normalised := normalise_history_item(item, "history")) is not None
    ]
    sport_events = [
        {**item, "category": "sport"}
        for item in normalised_events
        if history_keyword_score(str(item.get("text", "")), HISTORY_SPORT_KEYWORDS, 1) > 0
    ]
    history_events = [
        item
        for item in normalised_events
        if history_keyword_score(str(item.get("text", "")), HISTORY_SPORT_KEYWORDS, 1) == 0
    ]
    birth_events = [
        normalised
        for item in births
        if (normalised := normalise_history_item(item, "born")) is not None
    ] if isinstance(births, list) else []
    famous_birth_events = [
        item
        for item in birth_events
        if history_keyword_score(str(item.get("text", "")), HISTORY_FAMOUS_BIRTH_KEYWORDS, 1) > 0
    ] or birth_events

    selected: list[dict[str, Any]] = []
    selected.extend(ranked_history_items(history_events, "history")[: max(2, limit - 3)])
    selected.extend(ranked_history_items(sport_events, "sport")[:1])
    selected.extend(ranked_history_items(famous_birth_events, "born")[:2])

    if len(selected) < limit:
        selected_keys = {
            (item.get("category"), item.get("year"), item.get("text")) for item in selected
        }
        fallback_pool = ranked_history_items(
            [*history_events, *sport_events, *birth_events],
            "history",
        )
        for item in fallback_pool:
            key = (item.get("category"), item.get("year"), item.get("text"))
            if key in selected_keys:
                continue
            selected.append(item)
            selected_keys.add(key)
            if len(selected) >= limit:
                break

    return selected[:limit]


def history_payload(
    location: str,
    date_value: str,
    lang: str,
    limit_facts: int,
    limit_events: int,
) -> tuple[dict[str, Any], int]:
    location = normalise_history_location(location)
    parsed_date = parse_history_date(date_value)
    if not location:
        return {"error": "Location is required."}, HTTPStatus.BAD_REQUEST
    if parsed_date is None:
        return {"error": "Date must be a valid YYYY-MM-DD date."}, HTTPStatus.BAD_REQUEST

    iso_date, month, day = parsed_date
    cache_key = f"{lang}:{location.lower()}:{iso_date}:{limit_facts}:{limit_events}"
    cached = history_cache_get(cache_key)
    if cached is not None:
        return cached, HTTPStatus.OK

    warnings: list[dict[str, str]] = []
    location_payload: dict[str, Any] | None = None
    global_events: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=2) as executor:
        wiki_future = executor.submit(fetch_wikipedia_summary, location, lang)
        events_future = executor.submit(fetch_history_events, month, day, limit_events)

        try:
            wiki = wiki_future.result()
            content_urls = wiki.get("content_urls", {})
            desktop_urls = content_urls.get("desktop", {}) if isinstance(content_urls, dict) else {}
            thumbnail = wiki.get("thumbnail", {})
            article_url = desktop_urls.get("page")
            plain_extract = ""
            wikidata_entity = None

            try:
                plain_extract = fetch_wikipedia_plain_extract(str(wiki.get("title") or location), lang)
            except Exception as error:
                safe_log(f"History Wikipedia extract fetch failed: {error}")

            qid = str(wiki.get("wikibase_item", ""))
            if qid:
                try:
                    wikidata_entity = fetch_wikidata_entity(qid)
                except Exception as error:
                    safe_log(f"History Wikidata fetch failed: {error}")

            location_payload = {
                "title": wiki.get("title") or location,
                "description": wiki.get("description"),
                "profile": wikidata_profile(
                    wikidata_entity,
                    lang,
                    str(wiki.get("title") or location),
                ),
                "facts": build_location_facts(
                    wiki,
                    plain_extract,
                    limit_facts,
                    article_url,
                ),
                "articleUrl": article_url,
                "thumbnailUrl": thumbnail.get("source") if isinstance(thumbnail, dict) else None,
            }
        except LookupError:
            return {"error": f"No location facts found for {location}."}, HTTPStatus.NOT_FOUND
        except Exception as error:
            safe_log(f"History Wikipedia fetch failed: {error}")
            warnings.append(
                {
                    "source": "wikipedia",
                    "code": "upstream_unavailable",
                    "detail": "Location facts are currently unavailable.",
                }
            )

        try:
            global_events = events_future.result()
        except Exception as error:
            safe_log(f"History events fetch failed: {error}")
            warnings.append(
                {
                    "source": "history-muffinlabs",
                    "code": "upstream_unavailable",
                    "detail": "This day in history is currently unavailable.",
                }
            )

    if location_payload is None and not global_events:
        return {"error": "History sources are currently unavailable."}, HTTPStatus.SERVICE_UNAVAILABLE

    payload = {
        "request": {"location": location, "date": iso_date, "lang": lang},
        "location": location_payload,
        "globalEvents": global_events,
        "partial": bool(warnings),
        "warnings": warnings,
        "meta": {
            "cached": False,
            "eventsLanguage": "en",
            "generatedAt": utc_now(),
        },
    }
    history_cache_set(cache_key, payload)
    return payload, HTTPStatus.OK


class FultonsHandler(SimpleHTTPRequestHandler):
    server_version = "FultonsQuiz/0.1"

    def do_OPTIONS(self) -> None:
        origin = self.headers.get("Origin")
        if origin and not self.request_origin_allowed():
            self.send_error_json(HTTPStatus.FORBIDDEN, "Origin is not allowed.")
            return

        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-News-Monitor-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.end_headers()

    def end_headers(self) -> None:
        self.send_security_headers()
        self.send_cors_headers()
        super().end_headers()

    def send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(self)")
        if COOKIE_SECURE:
            self.send_header(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

    def cors_allowed_origin(self) -> str | None:
        origin = self.headers.get("Origin")
        if origin and origin in CORS_ALLOWED_ORIGINS:
            return origin
        return None

    def send_cors_headers(self) -> None:
        origin = self.cors_allowed_origin()
        if origin is None:
            return
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Vary", "Origin")

    def client_ip(self) -> str:
        return self.client_address[0] if self.client_address else "unknown"

    def request_origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        if origin in CORS_ALLOWED_ORIGINS:
            return True

        host = self.headers.get("Host", "")
        parsed_origin = urlparse(origin)
        if parsed_origin.netloc == host:
            return True

        if not COOKIE_SECURE and parsed_origin.hostname in {"127.0.0.1", "localhost"}:
            return True

        return False

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api("GET", parsed.path, parsed.query)
            return

        self.serve_static()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        self.handle_api("POST", parsed.path, parsed.query)

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        self.handle_api("PATCH", parsed.path, parsed.query)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        self.handle_api("DELETE", parsed.path, parsed.query)

    def send_json(
        self,
        status: int,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status: int, message: str) -> None:
        self.send_json(status, {"error": message})

    def send_sse_headers(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

    def write_sse(self, event: str, payload: dict[str, Any]) -> None:
        message = f"event: {event}\ndata: {json.dumps(payload)}\n\n"
        self.wfile.write(message.encode("utf-8"))
        self.wfile.flush()

    def read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length == 0:
            return {}
        if content_length > 1_000_000:
            raise ValueError("Request body is too large.")

        raw_body = self.rfile.read(content_length)
        if not raw_body:
            return {}

        decoded = json.loads(raw_body.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("Expected a JSON object.")
        return decoded

    def handle_api(self, method: str, path: str, query: str = "") -> None:
        try:
            if method in {"POST", "PATCH", "DELETE"} and not self.request_origin_allowed():
                self.send_error_json(HTTPStatus.FORBIDDEN, "Origin is not allowed.")
                return
            self.route_api(method, path.rstrip("/") or "/", query)
        except json.JSONDecodeError:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid JSON body.")
        except ValueError as error:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as error:
            safe_log(f"API error: {error}")
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "Server error.")

    def route_api(self, method: str, path: str, query: str = "") -> None:
        params = parse_qs(query)

        if path == "/api/news/stream" and method == "GET":
            with connect_db() as conn:
                token = get_cookie_value(self.headers, SESSION_COOKIE)
                user = current_user(conn, token)
                if user is None:
                    self.send_error_json(HTTPStatus.UNAUTHORIZED, "Login required.")
                    return
            self.handle_news_stream()
            return

        with connect_db() as conn:
            token = get_cookie_value(self.headers, SESSION_COOKIE)
            user = current_user(conn, token)

            if path == "/api/health" and method == "GET":
                self.send_json(HTTPStatus.OK, {"ok": True, "date": today_game_date()})
                return

            if path == "/api/auth/login" and method == "POST":
                self.handle_login(conn)
                return

            if path == "/api/auth/logout" and method == "POST":
                if token is not None:
                    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                self.send_json(
                    HTTPStatus.OK,
                    {"ok": True},
                    {"Set-Cookie": clear_session_header()},
                )
                return

            if path == "/api/auth/me" and method == "GET":
                if user is None:
                    self.send_error_json(HTTPStatus.UNAUTHORIZED, "Login required.")
                    return
                self.send_json(HTTPStatus.OK, {"user": user_payload(user)})
                return

            if path == "/api/news/add" and method == "POST":
                self.handle_news_add(conn)
                return

            if user is None:
                self.send_error_json(HTTPStatus.UNAUTHORIZED, "Login required.")
                return

            if path == "/api/me" and method == "PATCH":
                self.handle_update_me(conn, user)
                return

            if path == "/api/wordle/today" and method == "GET":
                game = ensure_daily_game(conn)
                self.send_json(
                    HTTPStatus.OK,
                    serialize_wordle_state(conn, user["id"], game),
                )
                return

            if path == "/api/daily-questions" and method == "GET":
                self.send_json(HTTPStatus.OK, ensure_daily_questions())
                return

            if path == "/api/daily-quiz/result" and method == "POST":
                payload = self.read_json()
                game_date = str(payload.get("date", "")).strip()
                category = str(payload.get("category", "")).strip()
                raw_answers = payload.get("answers", [])
                answers = raw_answers if isinstance(raw_answers, list) else []
                if not all(isinstance(answer, str) for answer in answers):
                    self.send_error_json(HTTPStatus.BAD_REQUEST, "Quiz answers must be text.")
                    return
                result_payload, status = save_daily_quiz_result(
                    conn,
                    user["id"],
                    game_date,
                    category,
                    answers,
                )
                self.send_json(status, result_payload)
                return

            if path == "/api/leaderboard" and method == "GET":
                self.send_json(HTTPStatus.OK, leaderboard_payload(conn))
                return

            if path in {"/api/history", "/api/facts"} and method == "GET":
                location = str(params.get("location", [""])[0]).strip()
                date_value = str(params.get("date", [today_game_date()])[0]).strip()
                lang = normalise_history_lang(params.get("lang", ["en"])[0])
                limit_facts = self.query_int(params, "limitFacts", 6, 1, 8)
                limit_events = self.query_int(params, "limitEvents", 5, 1, 10)
                payload, status = history_payload(
                    location,
                    date_value,
                    lang,
                    limit_facts,
                    limit_events,
                )
                self.send_json(status, payload)
                return

            category_match = re.fullmatch(r"/api/daily-questions/(football|general)", path)
            if category_match is not None and method == "GET":
                payload = ensure_daily_questions()
                category = category_match.group(1)
                self.send_json(
                    HTTPStatus.OK,
                    {"date": payload["date"], "questions": payload[category]},
                )
                return

            if path == "/api/news" and method == "GET":
                limit = self.query_int(params, "limit", NEWS_LIMIT_DEFAULT, 1, NEWS_LIMIT_MAX)
                category = params.get("category", ["all"])[0]
                if category not in {"all", "breaking", "news", "live-scores"}:
                    category = "all"
                self.send_json(
                    HTTPStatus.OK,
                    {"items": list_news_items(conn, limit, category), "category": category},
                )
                return

            validate_match = re.fullmatch(r"/api/wordle/validate/([A-Za-z]+)", path)
            if validate_match is not None and method == "GET":
                guess = validate_match.group(1).lower()
                self.send_json(HTTPStatus.OK, {"valid": valid_guess(guess)})
                return

            if path == "/api/wordle/guess" and method == "POST":
                self.handle_wordle_guess(conn, user)
                return

            if path.startswith("/api/admin/"):
                if not user_can_manage_players(user):
                    self.send_error_json(HTTPStatus.FORBIDDEN, "Player management access required.")
                    return
                self.handle_admin(conn, user, method, path)
                return

            self.send_error_json(HTTPStatus.NOT_FOUND, "API route not found.")

    def query_int(
        self,
        params: dict[str, list[str]],
        name: str,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        raw_value = params.get(name, [str(default)])[0]
        try:
            value = int(raw_value)
        except ValueError:
            return default
        return max(minimum, min(maximum, value))

    def handle_news_add(self, conn: sqlite3.Connection) -> None:
        if not NEWS_MONITOR_KEY:
            self.send_error_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "News monitor key is not configured.",
            )
            return

        submitted_key = self.headers.get("X-News-Monitor-Key", "")
        if not hmac.compare_digest(submitted_key, NEWS_MONITOR_KEY):
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Invalid news monitor key.")
            return

        item, inserted = upsert_news_item(conn, self.read_json())
        if inserted:
            broadcast_news_item(item)
        self.send_json(
            HTTPStatus.CREATED if inserted else HTTPStatus.OK,
            {"item": item, "inserted": inserted},
        )

    def handle_news_stream(self) -> None:
        stream: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=25)
        with NEWS_STREAMS_LOCK:
            NEWS_STREAMS.add(stream)

        try:
            self.send_sse_headers()
            self.write_sse("ready", {"ok": True, "date": today_game_date()})

            while True:
                try:
                    item = stream.get(timeout=20)
                    self.write_sse("news", item)
                except queue.Empty:
                    self.write_sse("ping", {"date": utc_now()})
        finally:
            with NEWS_STREAMS_LOCK:
                NEWS_STREAMS.discard(stream)

    def handle_login(self, conn: sqlite3.Connection) -> None:
        payload = self.read_json()
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
        client_ip = self.client_ip()

        if is_login_locked(username, client_ip):
            self.send_error_json(
                HTTPStatus.TOO_MANY_REQUESTS,
                "Too many login attempts. Try again later.",
            )
            return

        user = conn.execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(?)",
            (username,),
        ).fetchone()
        if user is None or not verify_password(password, user["password_hash"]):
            record_login_failure(username, client_ip)
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Invalid username or password.")
            return

        clear_login_failures(username, client_ip)
        token = create_session(conn, user["id"])
        self.send_json(
            HTTPStatus.OK,
            {"user": user_payload(user)},
            {"Set-Cookie": session_header(token)},
        )

    def handle_update_me(self, conn: sqlite3.Connection, user: sqlite3.Row) -> None:
        payload = self.read_json()
        new_username = payload.get("username")
        current_password = str(payload.get("currentPassword", ""))
        new_password = payload.get("newPassword")
        now = utc_now()

        if new_username is not None:
            normalized_username = str(new_username).strip()
            username_error = validate_username(normalized_username)
            if username_error is not None:
                self.send_error_json(HTTPStatus.BAD_REQUEST, username_error)
                return

            if normalized_username.lower() != user["username"].lower():
                try:
                    conn.execute(
                        "UPDATE users SET username = ?, updated_at = ? WHERE id = ?",
                        (normalized_username, now, user["id"]),
                    )
                except sqlite3.IntegrityError:
                    self.send_error_json(HTTPStatus.CONFLICT, "Username is already taken.")
                    return

        if new_password is not None and str(new_password):
            password = str(new_password)
            password_error = validate_password(password)
            if password_error is not None:
                self.send_error_json(HTTPStatus.BAD_REQUEST, password_error)
                return

            if not verify_password(current_password, user["password_hash"]):
                self.send_error_json(HTTPStatus.UNAUTHORIZED, "Current password is incorrect.")
                return

            conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (hash_password(password), now, user["id"]),
            )

        updated_user = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        self.send_json(HTTPStatus.OK, {"user": user_payload(updated_user)})

    def handle_wordle_guess(self, conn: sqlite3.Connection, user: sqlite3.Row) -> None:
        payload = self.read_json()
        guess = str(payload.get("guess", "")).strip().lower()
        words = load_word_list()

        if not valid_guess(guess, words):
            self.send_error_json(
                HTTPStatus.BAD_REQUEST,
                "Enter a valid five-letter word from the game list.",
            )
            return

        game = ensure_daily_game(conn)
        result = get_or_create_wordle_result(conn, user["id"], game["id"])

        if result["status"] != "in_progress":
            self.send_json(HTTPStatus.OK, serialize_wordle_state(conn, user["id"], game))
            return

        attempt_number = result["attempts_used"] + 1
        if attempt_number > MAX_ATTEMPTS:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "No attempts remain.")
            return

        feedback = serialize_feedback(compute_feedback(game["secret_word"], guess))
        won = all(tile["color"] == "green" for tile in feedback)
        status = "won" if won else "lost" if attempt_number >= MAX_ATTEMPTS else "in_progress"
        completed_at = utc_now() if status != "in_progress" else None
        score = wordle_score(status, attempt_number)
        now = utc_now()

        conn.execute(
            """
            INSERT INTO wordle_guesses
                (result_id, attempt_number, guess, feedback_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (result["id"], attempt_number, guess, json.dumps(feedback), now),
        )
        conn.execute(
            """
            UPDATE wordle_results
            SET status = ?, attempts_used = ?, score = ?, completed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, attempt_number, score, completed_at, now, result["id"]),
        )

        self.send_json(HTTPStatus.OK, serialize_wordle_state(conn, user["id"], game))

    def handle_admin(
        self,
        conn: sqlite3.Connection,
        user: sqlite3.Row,
        method: str,
        path: str,
    ) -> None:
        if path == "/api/admin/users" and method == "GET":
            rows = conn.execute(
                """
                SELECT
                    users.id,
                    users.username,
                    users.role,
                    users.is_moderator,
                    users.created_at,
                    SUM(CASE WHEN wordle_results.status IN ('won', 'lost') THEN 1 ELSE 0 END)
                        AS games_played,
                    SUM(CASE WHEN wordle_results.status = 'won' THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN wordle_results.status = 'lost' THEN 1 ELSE 0 END) AS losses
                FROM users
                LEFT JOIN wordle_results ON wordle_results.user_id = users.id
                WHERE ? = 'admin' OR (users.role = 'user' AND users.is_moderator = 0)
                GROUP BY users.id
                ORDER BY users.role ASC, LOWER(users.username)
                """
                ,
                (user["role"],),
            ).fetchall()
            self.send_json(HTTPStatus.OK, {"users": [admin_user_payload(row) for row in rows]})
            return

        if path == "/api/admin/users" and method == "POST":
            payload = self.read_json()
            username = str(payload.get("username", "")).strip()
            password = str(payload.get("password", ""))
            role = str(payload.get("role", "user"))

            username_error = validate_username(username)
            password_error = validate_password(password)
            if username_error is not None:
                self.send_error_json(HTTPStatus.BAD_REQUEST, username_error)
                return
            if password_error is not None:
                self.send_error_json(HTTPStatus.BAD_REQUEST, password_error)
                return
            if role not in {"admin", "mod", "user"}:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Role must be admin, mod, or user.")
                return
            if user["role"] != "admin" and role != "user":
                self.send_error_json(HTTPStatus.FORBIDDEN, "Moderators can only add players.")
                return

            now = utc_now()
            stored_role = "admin" if role == "admin" else "user"
            is_moderator = 1 if role == "mod" else 0
            try:
                conn.execute(
                    """
                    INSERT INTO users (
                        username, password_hash, role, is_moderator, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (username, hash_password(password), stored_role, is_moderator, now, now),
                )
            except sqlite3.IntegrityError:
                self.send_error_json(HTTPStatus.CONFLICT, "Username is already taken.")
                return

            self.send_json(HTTPStatus.CREATED, {"ok": True})
            return

        reset_match = re.fullmatch(r"/api/admin/users/(\d+)/reset-password", path)
        if reset_match is not None and method == "POST":
            if user["role"] != "admin":
                self.send_error_json(HTTPStatus.FORBIDDEN, "Admin access required.")
                return
            target_id = int(reset_match.group(1))
            payload = self.read_json()
            password = str(payload.get("password", ""))
            password_error = validate_password(password)
            if password_error is not None:
                self.send_error_json(HTTPStatus.BAD_REQUEST, password_error)
                return

            cursor = conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (hash_password(password), utc_now(), target_id),
            )
            if cursor.rowcount == 0:
                self.send_error_json(HTTPStatus.NOT_FOUND, "User not found.")
                return

            conn.execute("DELETE FROM sessions WHERE user_id = ?", (target_id,))
            self.send_json(HTTPStatus.OK, {"ok": True})
            return

        delete_match = re.fullmatch(r"/api/admin/users/(\d+)", path)
        if delete_match is not None and method == "DELETE":
            target_id = int(delete_match.group(1))
            if target_id == user["id"]:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "You cannot delete your own account.")
                return

            target = conn.execute(
                "SELECT role, is_moderator FROM users WHERE id = ?",
                (target_id,),
            ).fetchone()
            if target is None:
                self.send_error_json(HTTPStatus.NOT_FOUND, "User not found.")
                return
            if user["role"] != "admin" and (
                target["role"] != "user" or target["is_moderator"]
            ):
                self.send_error_json(HTTPStatus.FORBIDDEN, "Moderators can only delete players.")
                return

            cursor = conn.execute("DELETE FROM users WHERE id = ?", (target_id,))
            if cursor.rowcount == 0:
                self.send_error_json(HTTPStatus.NOT_FOUND, "User not found.")
                return

            self.send_json(HTTPStatus.OK, {"ok": True})
            return

        self.send_error_json(HTTPStatus.NOT_FOUND, "Admin route not found.")

    def translate_path(self, path: str) -> str:
        parsed_path = urlparse(path).path
        if parsed_path == "/" or Path(parsed_path).suffix == "":
            return str(DIST_DIR / "index.html")

        target = (DIST_DIR / parsed_path.lstrip("/")).resolve()
        dist_root = DIST_DIR.resolve()
        if not str(target).startswith(str(dist_root)) or not target.is_file():
            return str(DIST_DIR / "index.html")
        return str(target)

    def serve_static(self) -> None:
        if not (DIST_DIR / "index.html").exists():
            self.send_error_json(
                HTTPStatus.NOT_FOUND,
                "Build the frontend first with npm run build, or use npm run dev with the API server.",
            )
            return
        super().do_GET()

    def log_message(self, format: str, *args: Any) -> None:
        safe_log(f"{self.address_string()} - {format % args}")


def run() -> None:
    initialize_database()
    try:
        ensure_daily_questions()
    except Exception as error:  # pragma: no cover - startup logging guard
        safe_log(f"Daily quiz preload failed: {error}")
    start_news_monitor()
    host = os.environ.get("FULTONS_HOST", "127.0.0.1")
    port = int(os.environ.get("FULTONS_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), FultonsHandler)
    safe_log(f"Fulton's Quiz server running at http://{host}:{port}")
    safe_log(f"SQLite database: {DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    run()

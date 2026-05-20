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
NEWS_QUERIES = (
    '"St Mirren"',
    '"St Mirren" football',
    '"St Mirren" transfer',
    '"St Mirren" Scottish Premiership',
    '"St Mirren" live score',
    '"Scottish Premiership" live scores',
)
SUPPORTED_HISTORY_LANGS = {"en", "fr", "de", "es", "it"}

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
            ensure_column(conn, "daily_wordle_games", "cycle", "INTEGER NOT NULL DEFAULT 1")
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


def user_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


def admin_user_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
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


def wordle_stats(conn: sqlite3.Connection, user_id: int) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
            SUM(CASE WHEN status IN ('won', 'lost') THEN 1 ELSE 0 END) AS played,
            SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN status = 'lost' THEN 1 ELSE 0 END) AS losses
        FROM wordle_results
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    return {
        "played": row["played"] or 0,
        "wins": row["wins"] or 0,
        "losses": row["losses"] or 0,
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
            "guesses": guesses,
            "answer": game["secret_word"] if status != "in_progress" else None,
        },
        "stats": wordle_stats(conn, user_id),
    }


def default_daily_questions(game_date: str) -> dict[str, Any]:
    return {
        "date": game_date,
        "football": [
            {
                "difficulty": "easy",
                "question": "Which club plays its home matches at Anfield?",
                "answers": ["Liverpool", "Everton", "Celtic", "Leeds United"],
                "correct_answer": "Liverpool",
                "explanation": "Anfield is the home stadium of Liverpool FC.",
            },
            {
                "difficulty": "medium",
                "question": "Which nation won UEFA Euro 2016?",
                "answers": ["France", "Portugal", "Germany", "Spain"],
                "correct_answer": "Portugal",
                "explanation": "Portugal beat France 1-0 after extra time in the final.",
            },
            {
                "difficulty": "hard",
                "question": (
                    "Who scored the winning goal for Manchester United in the "
                    "1999 UEFA Champions League final?"
                ),
                "answers": [
                    "Teddy Sheringham",
                    "Ole Gunnar Solskjaer",
                    "David Beckham",
                    "Ryan Giggs",
                ],
                "correct_answer": "Ole Gunnar Solskjaer",
                "explanation": "Solskjaer scored in stoppage time to complete the comeback.",
            },
        ],
        "general": [
            {
                "difficulty": "easy",
                "question": "What is the capital city of France?",
                "answers": ["Paris", "Lyon", "Marseille", "Nice"],
                "correct_answer": "Paris",
                "explanation": "Paris is the capital of France.",
            },
            {
                "difficulty": "medium",
                "question": "Which element has the chemical symbol Au?",
                "answers": ["Silver", "Iron", "Gold", "Argon"],
                "correct_answer": "Gold",
                "explanation": "Au comes from the Latin word aurum.",
            },
            {
                "difficulty": "hard",
                "question": (
                    "In which year was the first successful human heart "
                    "transplant performed?"
                ),
                "answers": ["1958", "1967", "1974", "1981"],
                "correct_answer": "1967",
                "explanation": (
                    "The first successful human heart transplant was performed in 1967."
                ),
            },
        ],
    }


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


def daily_questions_path(game_date: str) -> Path:
    return QUIZ_DATA_DIR / f"daily-questions-{game_date}.json"


def ensure_daily_questions() -> dict[str, Any]:
    game_date = today_game_date()
    QUIZ_DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = daily_questions_path(game_date)

    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and validate_daily_questions(payload):
                return payload
        except (OSError, json.JSONDecodeError):
            pass

    payload = default_daily_questions(game_date)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(path)
    return payload


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


def classify_news_item(
    title: str,
    summary: str,
    tags: list[str],
) -> tuple[str, list[str]]:
    haystack = f"{title} {summary}".lower()
    clean_tags = list(dict.fromkeys(tags))

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
    breaking_terms = (
        "breaking",
        "confirmed",
        "signs",
        "signing",
        "transfer",
        "injury",
        "sacked",
        "appointed",
        "contract",
        "deal",
        "exclusive",
        "urgent",
    )

    if any(term in haystack for term in live_score_terms):
        clean_tags.append("live-scores")
        return "live-scores", list(dict.fromkeys(clean_tags))

    if any(term in haystack for term in breaking_terms):
        clean_tags.append("breaking")
        return "breaking", list(dict.fromkeys(clean_tags))

    clean_tags.append("news")
    return "news", list(dict.fromkeys(clean_tags))


def backfill_news_categories(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, title, summary, tags_json
        FROM news_items
        WHERE priority NOT IN ('breaking', 'news', 'live-scores')
        """
    ).fetchall()

    for row in rows:
        try:
            tags = json.loads(row["tags_json"])
        except json.JSONDecodeError:
            tags = []
        clean_tags = tags if isinstance(tags, list) else []
        priority, next_tags = classify_news_item(row["title"], row["summary"], clean_tags)
        conn.execute(
            """
            UPDATE news_items
            SET priority = ?, tags_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (priority, json.dumps(next_tags[:8]), utc_now(), row["id"]),
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


def wikipedia_summary_url(lang: str, title: str) -> str:
    safe_title = quote_plus(title.replace(" ", "_"), safe=",")
    return f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{safe_title}"


def fetch_wikipedia_summary(location: str, lang: str) -> dict[str, Any]:
    try:
        return fetch_json_url(wikipedia_summary_url(lang, location))
    except Exception:
        search_url = (
            f"https://{lang}.wikipedia.org/w/rest.php/v1/search/page"
            f"?q={quote_plus(location)}&limit=1"
        )
        search = fetch_json_url(search_url)
        pages = search.get("pages")
        if not isinstance(pages, list) or not pages:
            raise LookupError("Location not found.")

        title = pages[0].get("title")
        if not title:
            raise LookupError("Location not found.")
        return fetch_json_url(wikipedia_summary_url(lang, str(title)))


def text_facts_from_extract(extract: str, limit: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", str(extract or ""))
    return [sentence.strip() for sentence in sentences if sentence.strip()][:limit]


def fetch_history_events(month: int, day: int, limit: int) -> list[dict[str, Any]]:
    payload = fetch_json_url(f"https://history.muffinlabs.com/date/{month}/{day}")
    events = payload.get("data", {}).get("Events", [])
    if not isinstance(events, list):
        return []

    return [
        {
            "year": str(item.get("year", "")),
            "text": str(item.get("text", "")),
            "links": item.get("links", []) if isinstance(item.get("links"), list) else [],
        }
        for item in events[:limit]
        if isinstance(item, dict) and item.get("text")
    ]


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
            location_payload = {
                "title": wiki.get("title") or location,
                "description": wiki.get("description"),
                "facts": text_facts_from_extract(str(wiki.get("extract", "")), limit_facts),
                "articleUrl": desktop_urls.get("page"),
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
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
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

            if path == "/api/history" and method == "GET":
                location = str(params.get("location", [""])[0]).strip()
                date_value = str(params.get("date", [today_game_date()])[0]).strip()
                lang = normalise_history_lang(params.get("lang", ["en"])[0])
                limit_facts = self.query_int(params, "limitFacts", 3, 1, 5)
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
                if user["role"] != "admin":
                    self.send_error_json(HTTPStatus.FORBIDDEN, "Admin access required.")
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
            SET status = ?, attempts_used = ?, completed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, attempt_number, completed_at, now, result["id"]),
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
                    users.created_at,
                    SUM(CASE WHEN wordle_results.status IN ('won', 'lost') THEN 1 ELSE 0 END)
                        AS games_played,
                    SUM(CASE WHEN wordle_results.status = 'won' THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN wordle_results.status = 'lost' THEN 1 ELSE 0 END) AS losses
                FROM users
                LEFT JOIN wordle_results ON wordle_results.user_id = users.id
                GROUP BY users.id
                ORDER BY users.role ASC, LOWER(users.username)
                """
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
            if role not in {"admin", "user"}:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Role must be admin or user.")
                return

            now = utc_now()
            try:
                conn.execute(
                    """
                    INSERT INTO users (username, password_hash, role, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (username, hash_password(password), role, now, now),
                )
            except sqlite3.IntegrityError:
                self.send_error_json(HTTPStatus.CONFLICT, "Username is already taken.")
                return

            self.send_json(HTTPStatus.CREATED, {"ok": True})
            return

        reset_match = re.fullmatch(r"/api/admin/users/(\d+)/reset-password", path)
        if reset_match is not None and method == "POST":
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
    start_news_monitor()
    host = os.environ.get("FULTONS_HOST", "127.0.0.1")
    port = int(os.environ.get("FULTONS_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), FultonsHandler)
    safe_log(f"Fulton's Quiz server running at http://{host}:{port}")
    safe_log(f"SQLite database: {DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    run()

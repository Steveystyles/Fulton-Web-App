from __future__ import annotations

import hmac
import os
import sqlite3
import time
from contextlib import closing
from http import HTTPStatus
from typing import Any

import server

MIN_PASSWORD_LENGTH = int(os.environ.get("FULTONS_MIN_PASSWORD_LENGTH", "12"))
SEED_DEMO_USERS = os.environ.get("FULTONS_SEED_DEMO_USERS", "0") == "1"
COOKIE_SECURE = os.environ.get("FULTONS_COOKIE_SECURE", "1") == "1"
LOGIN_WINDOW_SECONDS = int(os.environ.get("FULTONS_LOGIN_WINDOW_SECONDS", "300"))
LOGIN_MAX_ATTEMPTS = int(
    os.environ.get("FULTONS_LOGIN_MAX_ATTEMPTS", os.environ.get("FULTONS_LOGIN_MAX_FAILURES", "5"))
)
LOGIN_BACKOFF_SECONDS = int(
    os.environ.get(
        "FULTONS_LOGIN_BACKOFF_SECONDS",
        os.environ.get("FULTONS_LOGIN_LOCKOUT_SECONDS", "60"),
    )
)
BOOTSTRAP_ADMIN_USERNAME = os.environ.get("FULTONS_BOOTSTRAP_ADMIN_USERNAME", "").strip()
BOOTSTRAP_ADMIN_PASSWORD = os.environ.get("FULTONS_BOOTSTRAP_ADMIN_PASSWORD", "")

FAILED_LOGINS: dict[str, list[float]] = {}


def _allowed_origins() -> set[str]:
    raw = os.environ.get("FULTONS_ALLOWED_ORIGINS", "")
    return {origin.strip() for origin in raw.split(",") if origin.strip()}


def validate_password(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    return None


def _bootstrap_admin_error() -> str | None:
    if not BOOTSTRAP_ADMIN_USERNAME and not BOOTSTRAP_ADMIN_PASSWORD:
        return None
    if not BOOTSTRAP_ADMIN_USERNAME or not BOOTSTRAP_ADMIN_PASSWORD:
        return "set both FULTONS_BOOTSTRAP_ADMIN_USERNAME and FULTONS_BOOTSTRAP_ADMIN_PASSWORD"

    username_error = server.validate_username(BOOTSTRAP_ADMIN_USERNAME)
    if username_error is not None:
        return f"bootstrap username invalid: {username_error}"

    password_error = validate_password(BOOTSTRAP_ADMIN_PASSWORD)
    if password_error is not None:
        return f"bootstrap password invalid: {password_error}"

    return None


def session_header(token: str) -> str:
    max_age = server.SESSION_DAYS * 24 * 60 * 60
    secure = "; Secure" if COOKIE_SECURE else ""
    return (
        f"{server.SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; "
        f"Max-Age={max_age}{secure}"
    )


def clear_session_header() -> str:
    secure = "; Secure" if COOKIE_SECURE else ""
    return f"{server.SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0{secure}"


def initialize_database() -> None:
    with closing(server.connect_db()) as conn:
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
            server.ensure_column(conn, "daily_wordle_games", "cycle", "INTEGER NOT NULL DEFAULT 1")
            user_count = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
            if user_count == 0:
                bootstrap_error = _bootstrap_admin_error()
                if bootstrap_error is None and BOOTSTRAP_ADMIN_USERNAME and BOOTSTRAP_ADMIN_PASSWORD:
                    server.seed_user(conn, BOOTSTRAP_ADMIN_USERNAME, BOOTSTRAP_ADMIN_PASSWORD, "admin")
                    server.safe_log(f"Bootstrapped admin user {BOOTSTRAP_ADMIN_USERNAME!r}")
                elif SEED_DEMO_USERS:
                    server.seed_user(conn, "admin", "adminadmin123", "admin")
                    server.seed_user(conn, "user1", "user1user1234", "user")
                    server.seed_user(conn, "user2", "user2user1234", "user")
                    server.safe_log("Seeded demo users because FULTONS_SEED_DEMO_USERS=1")
                else:
                    if bootstrap_error is not None:
                        server.safe_log(f"Admin bootstrap skipped: {bootstrap_error}")
                    server.safe_log("No users exist and demo seeding is disabled.")
            server.backfill_news_categories(conn)


def _client_key(handler: server.FultonsHandler, username: str) -> str:
    forwarded_for = handler.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        remote = forwarded_for.split(",", 1)[0].strip()
    else:
        remote = handler.client_address[0]
    return f"{remote}:{username.lower()}"


def _is_limited(key: str) -> bool:
    now = time.time()
    attempts = [stamp for stamp in FAILED_LOGINS.get(key, []) if now - stamp <= LOGIN_WINDOW_SECONDS]
    FAILED_LOGINS[key] = attempts
    return len(attempts) >= LOGIN_MAX_ATTEMPTS


def _record_failure(key: str) -> None:
    FAILED_LOGINS.setdefault(key, []).append(time.time())


def _clear_failures(key: str) -> None:
    FAILED_LOGINS.pop(key, None)


def handle_login(self: server.FultonsHandler, conn: sqlite3.Connection) -> None:
    payload = self.read_json()
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    key = _client_key(self, username)

    if _is_limited(key):
        self.send_error_json(
            HTTPStatus.TOO_MANY_REQUESTS,
            f"Too many failed login attempts. Try again in {LOGIN_BACKOFF_SECONDS} seconds.",
        )
        return

    user = conn.execute(
        "SELECT * FROM users WHERE LOWER(username) = LOWER(?)",
        (username,),
    ).fetchone()
    if user is None or not server.verify_password(password, user["password_hash"]):
        _record_failure(key)
        self.send_error_json(HTTPStatus.UNAUTHORIZED, "Invalid username or password.")
        return

    _clear_failures(key)
    token = server.create_session(conn, user["id"])
    self.send_json(
        HTTPStatus.OK,
        {"user": server.user_payload(user)},
        {"Set-Cookie": session_header(token)},
    )


_original_end_headers = server.FultonsHandler.end_headers


def end_headers(self: server.FultonsHandler) -> None:
    self.send_header("X-Content-Type-Options", "nosniff")
    self.send_header("X-Frame-Options", "DENY")
    self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
    self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if COOKIE_SECURE:
        self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    _original_end_headers(self)


def do_OPTIONS(self: server.FultonsHandler) -> None:
    origin = self.headers.get("Origin", "")
    allowed = _allowed_origins()
    self.send_response(HTTPStatus.NO_CONTENT)
    if origin and origin in allowed:
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Credentials", "true")
    self.send_header("Access-Control-Allow-Headers", "Content-Type, X-News-Monitor-Key")
    self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
    self.end_headers()


def apply_hardening() -> None:
    server.validate_password = validate_password
    server.session_header = session_header
    server.clear_session_header = clear_session_header
    server.initialize_database = initialize_database
    server.FultonsHandler.handle_login = handle_login
    server.FultonsHandler.end_headers = end_headers
    server.FultonsHandler.do_OPTIONS = do_OPTIONS


if __name__ == "__main__":
    apply_hardening()
    server.run()

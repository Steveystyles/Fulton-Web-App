from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 fallback
    ZoneInfo = None  # type: ignore[assignment]

APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "fultons.db"
DIST_DIR = APP_DIR / "dist"
SESSION_COOKIE = "fultons_session"
SESSION_DAYS = 14
PASSWORD_ITERATIONS = 260_000
USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
SERVER_TZ_NAME = os.environ.get("FULTONS_TIMEZONE", "Europe/London")

sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(APP_DIR))

from wordle_game import (  # noqa: E402
    MAX_ATTEMPTS,
    WORD_LENGTH,
    choose_secret,
    compute_feedback,
    load_word_list,
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
    if len(password) < 4:
        return "Use at least 4 characters."
    return None


def connect_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database() -> None:
    with connect_db() as conn:
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
            """
        )
        user_count = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
        if user_count == 0:
            seed_user(conn, "admin", "admin", "admin")
            seed_user(conn, "user1", "user1", "user")
            seed_user(conn, "user2", "user2", "user")


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


def session_header(token: str) -> str:
    max_age = SESSION_DAYS * 24 * 60 * 60
    return (
        f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; "
        f"Max-Age={max_age}"
    )


def clear_session_header() -> str:
    return f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"


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


def ensure_daily_game(conn: sqlite3.Connection) -> sqlite3.Row:
    game_date = today_game_date()
    game = conn.execute(
        "SELECT * FROM daily_wordle_games WHERE game_date = ?",
        (game_date,),
    ).fetchone()
    if game is not None:
        return game

    used_words = {
        row["secret_word"]
        for row in conn.execute("SELECT secret_word FROM daily_wordle_games")
    }
    secret_word = choose_secret(load_word_list(), used_words)
    now = utc_now()

    try:
        cursor = conn.execute(
            """
            INSERT INTO daily_wordle_games (game_date, secret_word, created_at)
            VALUES (?, ?, ?)
            """,
            (game_date, secret_word, now),
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


class FultonsHandler(SimpleHTTPRequestHandler):
    server_version = "FultonsQuiz/0.1"

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "*"))
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api("GET", parsed.path)
            return

        self.serve_static()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        self.handle_api("POST", parsed.path)

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        self.handle_api("PATCH", parsed.path)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        self.handle_api("DELETE", parsed.path)

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

    def handle_api(self, method: str, path: str) -> None:
        try:
            self.route_api(method, path.rstrip("/") or "/")
        except json.JSONDecodeError:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid JSON body.")
        except ValueError as error:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
        except Exception as error:
            safe_log(f"API error: {error}")
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "Server error.")

    def route_api(self, method: str, path: str) -> None:
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

    def handle_login(self, conn: sqlite3.Connection) -> None:
        payload = self.read_json()
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))

        user = conn.execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(?)",
            (username,),
        ).fetchone()
        if user is None or not verify_password(password, user["password_hash"]):
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Invalid username or password.")
            return

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
    host = os.environ.get("FULTONS_HOST", "127.0.0.1")
    port = int(os.environ.get("FULTONS_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), FultonsHandler)
    safe_log(f"Fulton's Quiz server running at http://{host}:{port}")
    safe_log(f"SQLite database: {DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    run()

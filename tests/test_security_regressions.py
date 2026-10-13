from __future__ import annotations

import ipaddress
import sqlite3
import tempfile
import threading
import unittest
from collections import deque
from contextlib import closing
from email.message import Message
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
from types import MethodType
from unittest.mock import patch

import safe_http
import server


class OutboundRequestSafetyTests(unittest.TestCase):
    def test_rejects_local_file_private_addresses_credentials_and_ports(self) -> None:
        blocked = (
            "file:///etc/passwd",
            "http://127.0.0.1/private",
            "http://169.254.169.254/latest/meta-data",
            "http://100.64.0.1/shared-address-space",
            "http://user:secret@example.com/",
            "https://example.com:444/",
        )
        for url in blocked:
            with self.subTest(url=url), self.assertRaises(safe_http.UnsafeOutboundUrl):
                safe_http.validate_public_http_url(url)

    def test_rejects_hostname_if_any_dns_answer_is_private(self) -> None:
        answers = [
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("10.0.0.8", 443)),
        ]
        with (
            patch("safe_http.socket.getaddrinfo", return_value=answers),
            self.assertRaises(safe_http.UnsafeOutboundUrl),
        ):
            safe_http.validate_public_http_url("https://example.test/path")

    def test_accepts_allowlisted_public_hostname(self) -> None:
        answers = [(2, 1, 6, "", ("93.184.216.34", 443))]
        with patch("safe_http.socket.getaddrinfo", return_value=answers):
            self.assertEqual(
                safe_http.validate_public_http_url(
                    "https://example.test/path",
                    allowed_hosts={"example.test"},
                ),
                "https://example.test/path",
            )

    def test_fetch_connects_to_the_single_dns_result_that_was_validated(self) -> None:
        answers = [(2, 1, 6, "", ("93.184.216.34", 443))]
        connected: list[tuple[str, int, str]] = []

        class Response:
            status = 200
            reason = "OK"
            headers = Message()

            def read(self, _limit: int) -> bytes:
                return b"safe"

            def close(self) -> None:
                return None

        class Connection:
            def __init__(
                self,
                host: str,
                port: int,
                address: str,
                *,
                timeout: float,
            ) -> None:
                del timeout
                connected.append((host, port, address))

            def request(self, *_args: object, **_kwargs: object) -> None:
                return None

            def getresponse(self) -> Response:
                return Response()

            def close(self) -> None:
                return None

        with (
            patch("safe_http.socket.getaddrinfo", return_value=answers) as resolve,
            patch("safe_http._PinnedHTTPSConnection", Connection),
        ):
            body, _charset = safe_http.fetch_public_bytes(
                "https://example.test/path",
                timeout=1,
            )

        self.assertEqual(body, b"safe")
        self.assertEqual(connected, [("example.test", 443, "93.184.216.34")])
        resolve.assert_called_once()

    def test_redirect_to_private_network_is_rejected_before_second_connection(self) -> None:
        answers = [(2, 1, 6, "", ("93.184.216.34", 80))]
        headers = Message()
        headers["Location"] = "http://127.0.0.1/internal"

        class Response:
            status = 302
            reason = "Found"

            def __init__(self) -> None:
                self.headers = headers

            def close(self) -> None:
                return None

        class Connection:
            calls = 0

            def __init__(self, *_args: object, **_kwargs: object) -> None:
                type(self).calls += 1

            def request(self, *_args: object, **_kwargs: object) -> None:
                return None

            def getresponse(self) -> Response:
                return Response()

            def close(self) -> None:
                return None

        with (
            patch("safe_http.socket.getaddrinfo", return_value=answers),
            patch("safe_http._PinnedHTTPConnection", Connection),
            self.assertRaises(safe_http.UnsafeOutboundUrl),
        ):
            safe_http.fetch_public_bytes("http://example.test/", timeout=1)
        self.assertEqual(Connection.calls, 1)

    def test_bounded_reader_rejects_declared_chunked_and_compressed_overflow(self) -> None:
        class Response:
            def __init__(self, body: bytes, headers: dict[str, str]) -> None:
                self._body = body
                self.headers = Message()
                for key, value in headers.items():
                    self.headers[key] = value

            def read(self, limit: int) -> bytes:
                return self._body[:limit]

        cases = (
            Response(b"small", {"Content-Length": "100"}),
            Response(b"123456", {}),
            Response(b"small", {"Content-Encoding": "gzip"}),
        )
        for response in cases:
            with self.subTest(headers=dict(response.headers)), self.assertRaises(
                safe_http.ResponseTooLarge
            ):
                safe_http.read_bounded_response(response, max_bytes=5)  # type: ignore[arg-type]

    def test_bounded_reader_enforces_total_response_deadline(self) -> None:
        class Socket:
            timeout = 30.0

            def gettimeout(self) -> float:
                return self.timeout

            def settimeout(self, value: float) -> None:
                self.timeout = value

        class Response:
            def __init__(self) -> None:
                self.headers = Message()
                self.headers["Content-Length"] = "3"
                self.socket = Socket()
                self.fp = type("Buffer", (), {"raw": type("Raw", (), {"_sock": self.socket})()})()
                self.reads = 0

            def read1(self, _limit: int) -> bytes:
                self.reads += 1
                return b"x"

            def read(self, _limit: int) -> bytes:
                raise AssertionError("Deadline reader should use non-filling read1.")

        response = Response()
        with patch("safe_http.time.monotonic", side_effect=[0.0, 0.2, 1.1]):
            with self.assertRaisesRegex(TimeoutError, "exceeded its deadline"):
                safe_http.read_bounded_response(
                    response, max_bytes=5, max_duration_sec=1.0,
                )  # type: ignore[arg-type]
        self.assertEqual(response.reads, 1)
        self.assertEqual(response.socket.timeout, 30.0)

        response = Response()
        with patch("safe_http.time.monotonic", side_effect=[0.0, 0.1, 0.2, 0.3]):
            body, _charset = safe_http.read_bounded_response(
                response, max_bytes=5, max_duration_sec=1.0,
            )  # type: ignore[arg-type]
        self.assertEqual(body, b"xxx")
        self.assertEqual(response.socket.timeout, 30.0)


class AuthenticationSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        server.LOGIN_ATTEMPTS.clear()

    def tearDown(self) -> None:
        server.LOGIN_ATTEMPTS.clear()

    def test_release_migration_locks_current_and_past_quizzes_only(self) -> None:
        import daily_quiz

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        daily_quiz.initialize_database(conn)
        conn.executemany(
            "INSERT INTO daily_quiz_sets (quiz_date, status) VALUES (?, 'published')",
            [("2026-08-15",), ("2026-08-16",), ("2026-08-17",)],
        )
        with patch("server.today_game_date", return_value="2026-08-16"):
            server.backfill_released_quiz_locks(conn)

        locks = {
            str(row["quiz_date"]): row["locked_at"]
            for row in conn.execute(
                "SELECT quiz_date, locked_at FROM daily_quiz_sets ORDER BY quiz_date"
            )
        }
        self.assertIsNotNone(locks["2026-08-15"])
        self.assertIsNotNone(locks["2026-08-16"])
        self.assertIsNone(locks["2026-08-17"])
        conn.close()

    def test_new_session_is_hashed_and_plaintext_legacy_rows_are_migrated(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                password_hash TEXT,
                role TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER,
                created_at TEXT,
                expires_at TEXT
            );
            INSERT INTO users VALUES (1, 'tester', 'hash', 'user', '', '');
            """
        )
        token = server.create_session(conn, 1)
        stored = conn.execute("SELECT token FROM sessions").fetchone()["token"]
        self.assertNotEqual(stored, token)
        self.assertEqual(stored, server.session_token_digest(token))
        self.assertEqual(server.current_user(conn, token)["id"], 1)

        legacy = "legacy-plaintext-token"
        conn.execute(
            "INSERT INTO sessions VALUES (?, 1, ?, ?)",
            (legacy, server.utc_now(), "2999-01-01T00:00:00+00:00"),
        )
        server.migrate_plaintext_session_tokens(conn)
        migrated = conn.execute(
            "SELECT token FROM sessions WHERE user_id = 1 AND token = ?",
            (server.session_token_digest(legacy),),
        ).fetchone()
        self.assertIsNotNone(migrated)
        self.assertEqual(server.current_user(conn, legacy)["id"], 1)
        conn.close()

    def test_login_failures_expire_and_unique_invalid_usernames_do_not_grow_map(self) -> None:
        with (
            patch.object(server, "LOGIN_MAX_FAILURES", 3),
            patch.object(server, "LOGIN_WINDOW_SECONDS", 60),
            patch.object(server, "LOGIN_LOCKOUT_SECONDS", 30),
            patch.object(server, "LOGIN_ATTEMPT_BUCKET_LIMIT", 8),
            patch("server.time.time", return_value=100.0),
        ):
            for index in range(20):
                server.record_login_failure(f"invalid user {index}", "203.0.113.9")
            self.assertLessEqual(len(server.LOGIN_ATTEMPTS), 8)
            self.assertTrue(server.is_login_locked("another invalid", "203.0.113.9"))

        with patch("server.time.time", return_value=1000.0):
            self.assertFalse(server.is_login_locked("another invalid", "203.0.113.9"))

    def test_missing_user_still_runs_password_verification(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE users (username TEXT, password_hash TEXT)")
        sent: list[tuple[int, str]] = []

        class Handler:
            def read_json(self) -> dict[str, str]:
                return {"username": "missing", "password": "candidate"}

            def client_ip(self) -> str:
                return "203.0.113.4"

            def send_error_json(self, status: int, message: str) -> None:
                sent.append((status, message))

        with patch("server.verify_password", return_value=False) as verify:
            server.FultonsHandler.handle_login(Handler(), conn)  # type: ignore[arg-type]

        verify.assert_called_once_with("candidate", server.DUMMY_PASSWORD_HASH)
        self.assertEqual(sent[0][0], HTTPStatus.UNAUTHORIZED)
        conn.close()

    def test_login_fails_fast_when_password_verification_capacity_is_full(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE users (username TEXT, password_hash TEXT)")
        sent: list[tuple[int, str]] = []

        class FullGate:
            @staticmethod
            def acquire(*, blocking: bool) -> bool:
                self.assertFalse(blocking)
                return False

            @staticmethod
            def release() -> None:
                raise AssertionError("an unacquired verification slot must not be released")

        class Handler:
            def read_json(self) -> dict[str, str]:
                return {"username": "missing", "password": "candidate"}

            def client_ip(self) -> str:
                return "203.0.113.4"

            def send_error_json(self, status: int, message: str) -> None:
                sent.append((status, message))

        with (
            patch.object(server, "LOGIN_VERIFY_SEMAPHORE", FullGate()),
            patch("server.verify_password") as verify,
        ):
            server.FultonsHandler.handle_login(Handler(), conn)  # type: ignore[arg-type]

        verify.assert_not_called()
        self.assertEqual(sent[0][0], HTTPStatus.SERVICE_UNAVAILABLE)
        conn.close()

    def test_successful_login_records_audit_event_without_credentials(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE,
                password_hash TEXT,
                role TEXT
            );
            CREATE TABLE audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                actor_user_id INTEGER,
                target_user_id INTEGER,
                client_ip TEXT NOT NULL DEFAULT '',
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO users VALUES (1, 'player', ?, 'user')",
            (server.hash_password("correct-password"),),
        )
        sent: list[tuple[int, dict[str, object], dict[str, str]]] = []

        class Handler:
            def read_json(self) -> dict[str, str]:
                return {"username": "player", "password": "correct-password"}

            def client_ip(self) -> str:
                return "198.51.100.10"

            def send_error_json(self, *_args: object) -> None:
                raise AssertionError("valid login must not fail")

            def send_json(
                self,
                status: int,
                payload: dict[str, object],
                headers: dict[str, str],
            ) -> None:
                sent.append((status, payload, headers))

        with (
            patch("server.create_session", return_value="client-session-token"),
            patch("server.auth_payload", return_value={"user": {"id": 1}}),
            conn,
        ):
            server.FultonsHandler.handle_login(Handler(), conn)  # type: ignore[arg-type]

        event = conn.execute(
            "SELECT event_type, actor_user_id, target_user_id, client_ip, details_json "
            "FROM audit_events"
        ).fetchone()
        self.assertEqual(sent[0][0], HTTPStatus.OK)
        self.assertEqual(event["event_type"], "auth.login")
        self.assertEqual(event["actor_user_id"], 1)
        self.assertEqual(event["target_user_id"], 1)
        self.assertEqual(event["client_ip"], "198.51.100.10")
        self.assertNotIn("password", event["details_json"].casefold())
        self.assertNotIn("token", event["details_json"].casefold())
        conn.close()

    def test_profile_error_does_not_partially_update_username(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        now = server.utc_now()
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE,
                password_hash TEXT,
                role TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER,
                created_at TEXT,
                expires_at TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO users VALUES (1, 'before', ?, 'user', ?, ?)",
            (server.hash_password("correct-password"), now, now),
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE id = 1").fetchone()
        sent: list[tuple[int, str]] = []

        class Handler:
            def read_json(self) -> dict[str, str]:
                return {
                    "username": "after",
                    "currentPassword": "wrong-password",
                    "newPassword": "replacement-password",
                }

            def send_error_json(self, status: int, message: str) -> None:
                sent.append((status, message))

            def send_json(self, *_args: object, **_kwargs: object) -> None:
                raise AssertionError("invalid request must not succeed")

        with conn:
            server.FultonsHandler.handle_update_me(Handler(), conn, user)  # type: ignore[arg-type]

        self.assertEqual(sent[0][0], HTTPStatus.UNAUTHORIZED)
        self.assertEqual(conn.execute("SELECT username FROM users").fetchone()[0], "before")
        conn.close()

    def test_successful_profile_update_records_transactional_audit_event(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        now = server.utc_now()
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE,
                password_hash TEXT,
                role TEXT,
                is_moderator INTEGER NOT NULL DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                actor_user_id INTEGER,
                target_user_id INTEGER,
                client_ip TEXT NOT NULL DEFAULT '',
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO users VALUES (1, 'before', ?, 'user', 0, ?, ?)",
            (server.hash_password("correct-password"), now, now),
        )
        user = conn.execute("SELECT * FROM users WHERE id = 1").fetchone()

        class Handler:
            def read_json(self) -> dict[str, str]:
                return {"username": "after"}

            def client_ip(self) -> str:
                return "198.51.100.9"

            def send_error_json(self, *_args: object) -> None:
                raise AssertionError("valid request must not fail")

            def send_json(self, *_args: object, **_kwargs: object) -> None:
                return None

        with conn:
            server.FultonsHandler.handle_update_me(Handler(), conn, user)  # type: ignore[arg-type]

        event = conn.execute(
            "SELECT event_type, actor_user_id, target_user_id, client_ip, details_json "
            "FROM audit_events"
        ).fetchone()
        self.assertEqual(event["event_type"], "account.profile_update")
        self.assertEqual(event["actor_user_id"], 1)
        self.assertEqual(event["target_user_id"], 1)
        self.assertEqual(event["client_ip"], "198.51.100.9")
        self.assertIn('"usernameChanged":true', event["details_json"])
        conn.close()


class RequestHandlingSafetyTests(unittest.TestCase):
    def test_negative_content_length_is_rejected_before_read(self) -> None:
        class Handler:
            headers = {"Content-Length": "-1", "Content-Type": "application/json"}
            rfile = BytesIO(b'{"ignored": true}')

        with self.assertRaisesRegex(ValueError, "non-negative"):
            server.FultonsHandler.read_json(Handler())  # type: ignore[arg-type]

    def test_cookie_mutation_requires_origin_and_host_is_allowlisted(self) -> None:
        class Handler:
            headers = {
                "Host": "fultons-quiz.co.uk",
                "Cookie": "fultons_session=token",
            }

        handler = Handler()
        self.assertTrue(server.FultonsHandler.request_host_allowed(handler))  # type: ignore[arg-type]
        self.assertFalse(server.FultonsHandler.request_origin_allowed(handler))  # type: ignore[arg-type]
        handler.headers["Origin"] = "https://fultons-quiz.co.uk"
        self.assertTrue(server.FultonsHandler.request_origin_allowed(handler))  # type: ignore[arg-type]
        handler.headers["Host"] = "attacker.example"
        self.assertFalse(server.FultonsHandler.request_host_allowed(handler))  # type: ignore[arg-type]

    def test_proxy_headers_are_used_only_for_explicitly_trusted_peers(self) -> None:
        class Handler:
            headers = {
                "X-Forwarded-For": "192.0.2.10, 198.51.100.20",
                "X-Real-IP": "203.0.113.30",
            }
            client_address = ("172.18.0.2", 12345)

        handler = Handler()
        proxy_network = ipaddress.ip_network("172.18.0.0/16")
        with patch.object(server, "TRUST_PROXY_HEADERS", False):
            self.assertEqual(
                server.FultonsHandler.client_ip(handler),  # type: ignore[arg-type]
                "172.18.0.2",
            )
        with (
            patch.object(server, "TRUST_PROXY_HEADERS", True),
            patch.object(server, "TRUSTED_PROXY_NETWORKS", (proxy_network,)),
        ):
            self.assertEqual(
                server.FultonsHandler.client_ip(handler),  # type: ignore[arg-type]
                "198.51.100.20",
            )
            handler.headers["X-Forwarded-For"] = "invalid, 198.51.100.20"
            self.assertEqual(
                server.FultonsHandler.client_ip(handler),  # type: ignore[arg-type]
                "172.18.0.2",
            )

    def test_forwarded_clients_do_not_share_the_ip_login_bucket(self) -> None:
        server.LOGIN_ATTEMPTS.clear()
        self.addCleanup(server.LOGIN_ATTEMPTS.clear)
        proxy_network = ipaddress.ip_network("172.18.0.0/16")

        class Handler:
            client_address = ("172.18.0.2", 12345)

            def __init__(self, client: str) -> None:
                self.headers = {"X-Forwarded-For": client}

        first = Handler("192.0.2.10")
        second = Handler("198.51.100.20")
        with (
            patch.object(server, "TRUST_PROXY_HEADERS", True),
            patch.object(server, "TRUSTED_PROXY_NETWORKS", (proxy_network,)),
            patch.object(server, "LOGIN_MAX_FAILURES", 3),
            patch.object(server, "LOGIN_WINDOW_SECONDS", 60),
            patch.object(server, "LOGIN_LOCKOUT_SECONDS", 30),
            patch("server.time.time", return_value=100.0),
        ):
            first_ip = server.FultonsHandler.client_ip(first)  # type: ignore[arg-type]
            second_ip = server.FultonsHandler.client_ip(second)  # type: ignore[arg-type]
            for _ in range(3):
                server.record_login_failure("candidate", first_ip)
            self.assertTrue(server.is_login_locked("someone", first_ip))
            self.assertFalse(server.is_login_locked("someone", second_ip))

    def test_success_json_is_not_written_if_route_raises_after_queueing_it(self) -> None:
        handler = object.__new__(server.FultonsHandler)
        handler.headers = {"Host": "localhost"}
        written: list[tuple[int, dict[str, object], object]] = []

        def write_json(
            _self: object,
            status: int,
            payload: dict[str, object],
            headers: object = None,
        ) -> None:
            written.append((status, payload, headers))

        handler._write_json = MethodType(write_json, handler)  # type: ignore[method-assign]

        def failing_route(
            self: server.FultonsHandler,
            _method: str,
            _path: str,
            _query: str = "",
        ) -> None:
            self.send_json(HTTPStatus.OK, {"ok": True})
            raise sqlite3.OperationalError("commit failed")

        with patch.object(server.FultonsHandler, "route_api", failing_route):
            server.FultonsHandler.handle_api(handler, "GET", "/api/test")

        self.assertEqual(len(written), 1)
        self.assertEqual(written[0][0], HTTPStatus.INTERNAL_SERVER_ERROR)


class WordleConcurrencyTests(unittest.TestCase):
    def test_get_or_create_result_is_atomic_across_connections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "wordle.db"
            setup = sqlite3.connect(db_path)
            setup.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE wordle_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    game_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    attempts_used INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, game_id)
                );
                """
            )
            setup.close()
            barrier = threading.Barrier(2)
            errors: list[Exception] = []

            def create() -> None:
                conn = sqlite3.connect(db_path, timeout=5)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA busy_timeout = 5000")
                try:
                    barrier.wait()
                    with conn:
                        result = server.get_or_create_wordle_result(conn, 1, 1)
                        self.assertIsNotNone(result)
                except Exception as error:  # pragma: no cover - asserted below
                    errors.append(error)
                finally:
                    conn.close()

            threads = [threading.Thread(target=create) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])
            with closing(sqlite3.connect(db_path)) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM wordle_results").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()

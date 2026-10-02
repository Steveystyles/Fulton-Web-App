from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone, tzinfo
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class ProductionServerHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def test_password_policy_requires_longer_passwords(self) -> None:
        import server

        self.assertIsNotNone(server.validate_password("short"))
        self.assertIsNone(server.validate_password("correct-horse-battery"))

    def test_session_cookie_can_be_marked_secure(self) -> None:
        import server

        with patch.object(server, "COOKIE_SECURE", True):
            header = server.session_header("token-value")
        self.assertIn("HttpOnly", header)
        self.assertIn("SameSite=Lax", header)
        self.assertIn("Secure", header)

    def test_daily_map_generation_rejects_truthy_string_force(self) -> None:
        import server

        sent_errors: list[tuple[HTTPStatus, str]] = []

        class DummyHandler:
            headers = {"Authorization": "Bearer test-token"}

            def read_json(self) -> dict[str, object]:
                return {"date": "2026-08-11", "force": "false"}

            def send_error_json(self, status: HTTPStatus, message: str) -> None:
                sent_errors.append((status, message))

        with (
            patch.object(
                server,
                "DAILY_QUIZ_CONFIG",
                SimpleNamespace(internal_token="test-token"),
            ),
            patch("server.generate_daily_map_game_for_date") as generate,
        ):
            server.FultonsHandler.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "POST",
                "/internal/generate-daily-map-game",
                "",
            )

        self.assertEqual(
            sent_errors,
            [(HTTPStatus.BAD_REQUEST, "force must be a JSON boolean.")],
        )
        generate.assert_not_called()

    def test_retired_facts_history_apis_return_gone(self) -> None:
        import server

        responses: list[tuple[HTTPStatus, str]] = []

        class DummyHandler:
            def send_error_json(self, status: HTTPStatus, message: str) -> None:
                responses.append((status, message))

        for path in ("/api/history", "/api/facts", "/api/fact-image"):
            for method in ("GET", "POST"):
                server.FultonsHandler.route_api(  # type: ignore[arg-type]
                    DummyHandler(),
                    method,
                    path,
                    "",
                )

        self.assertEqual(len(responses), 6)
        self.assertTrue(all(status == HTTPStatus.GONE for status, _message in responses))
        self.assertTrue(all("retired" in message.lower() for _status, message in responses))

    def test_current_user_avoids_session_cleanup_write_on_read_path(self) -> None:
        import server

        row = object()

        class DummyCursor:
            def fetchone(self) -> object:
                return row

        class DummyConnection:
            def __init__(self) -> None:
                self.statements: list[str] = []

            def execute(self, statement: str, _params: object = None) -> DummyCursor:
                self.statements.append(statement)
                if statement.lstrip().upper().startswith("DELETE FROM SESSIONS"):
                    raise AssertionError("current_user should not delete sessions during reads")
                return DummyCursor()

        conn = DummyConnection()

        user = server.current_user(conn, "token-123")

        self.assertIs(user, row)
        self.assertEqual(len(conn.statements), 1)
        self.assertIn("SELECT users.*", conn.statements[0])

    def test_map_promo_announcement_is_scoped_per_user(self) -> None:
        import server

        db_path = Path(self.temp_dir.name) / "announcements.db"
        with (
            patch.object(server, "DATA_DIR", db_path.parent),
            patch.object(server, "DB_PATH", db_path),
            patch.object(server, "SEED_DEMO_USERS", False),
            patch.object(server, "today_game_date", return_value="2026-08-04"),
        ):
            server.initialize_database()
            with closing(server.connect_db()) as conn, conn:
                now = server.utc_now()
                conn.execute(
                    """
                    INSERT INTO users (
                        username, password_hash, role, created_at, updated_at
                    ) VALUES ('one', 'hash', 'user', ?, ?), ('two', 'hash', 'user', ?, ?)
                    """,
                    (now, now, now, now),
                )
                users = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
                first = server.auth_payload(conn, users[0])
                second = server.auth_payload(conn, users[1])
                self.assertEqual(first["pendingAnnouncements"], second["pendingAnnouncements"])
                self.assertEqual(first["availableAnnouncements"], second["availableAnnouncements"])
                campaign_id = first["pendingAnnouncements"][0]["id"]
                conn.execute(
                    """
                    INSERT INTO user_announcement_acknowledgements (
                        user_id, campaign_id, action, acknowledged_at
                    ) VALUES (?, ?, 'played', ?)
                    """,
                    (users[0]["id"], campaign_id, now),
                )
                self.assertEqual(server.pending_announcements(conn, users[0]["id"]), [])
                self.assertEqual(
                    server.pending_announcements(conn, users[1]["id"])[0]["id"],
                    campaign_id,
                )

    def test_map_promo_is_hidden_until_launch_date(self) -> None:
        import server

        with (
            patch.object(server, "MAP_PROMO_AVAILABLE_DATE", "2026-08-04"),
            patch.object(server, "today_game_date", return_value="2026-08-03"),
        ):
            self.assertFalse(server.map_promo_is_available())
            self.assertEqual(server.available_announcements(), [])

        with (
            patch.object(server, "MAP_PROMO_AVAILABLE_DATE", "2026-08-04"),
            patch.object(server, "today_game_date", return_value="2026-08-04"),
        ):
            self.assertTrue(server.map_promo_is_available())
            self.assertEqual(
                server.available_announcements(),
                [{"id": server.MAP_PROMO_CAMPAIGN_ID, "kind": "daily-map-promo"}],
            )

    def test_ops_monitor_returns_disabled_payload_when_feature_is_off(self) -> None:
        import ops_monitor

        disabled = ops_monitor.MonitorConfig(
            enabled=False,
            cache_ttl_sec=15,
            ssh_target="",
            ssh_port=22,
            ssh_key_path="",
            ssh_connect_timeout_sec=6,
            public_health_url="https://example.com/api/health",
            internal_base_url="https://example.com",
            internal_quiz_token="secret-token",
            compose_file="/compose.yaml",
            env_file="/app.env",
            data_dir="/data",
            db_path="/data/fultons.db",
            app_port=3000,
        )

        with patch.object(ops_monitor.MonitorConfig, "from_env", return_value=disabled):
            payload = ops_monitor.collect_dashboard_snapshot()

        self.assertFalse(payload["enabled"])
        self.assertEqual(payload["status"], "disabled")
        self.assertIn("FULTONS_MONITOR_ENABLED", payload["reason"])

    def test_internal_get_routes_through_api_handler(self) -> None:
        import server

        calls: list[tuple[str, ...]] = []

        class DummyHandler:
            path = "/internal/ops-summary?force=1"

            def handle_api(self, method: str, path: str, query: str = "") -> None:
                calls.append((method, path, query))

            def serve_static(self) -> None:
                calls.append(("static",))

        server.FultonsHandler.do_GET(DummyHandler())  # type: ignore[arg-type]

        self.assertEqual(calls, [("GET", "/internal/ops-summary", "force=1")])

    def test_map_review_feedback_route_rejects_anonymous_submission(self) -> None:
        import server

        sent_errors: list[tuple[HTTPStatus, str]] = []

        class DummyHandler:
            headers: dict[str, str] = {}

            def send_error_json(self, status: HTTPStatus, message: str) -> None:
                sent_errors.append((status, message))

            def read_json(self) -> dict[str, object]:
                raise AssertionError("Unauthorized review body must not be read.")

        with (
            patch("server.connect_db") as connect_db,
            patch("server.get_cookie_value", return_value=None),
            patch("server.current_user", return_value=None),
        ):
            connect_db.return_value.__enter__.return_value = object()
            server.FultonsHandler.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "POST",
                "/api/map-place-review-feedback",
                "",
            )

        self.assertEqual(sent_errors, [(HTTPStatus.UNAUTHORIZED, "Login required.")])

    def test_map_review_feedback_route_allows_admin_to_reach_validation(self) -> None:
        import server

        sent_errors: list[tuple[HTTPStatus, str]] = []

        class DummyHandler:
            headers = {"Cookie": "fultons_session=token"}

            def send_error_json(self, status: HTTPStatus, message: str) -> None:
                sent_errors.append((status, message))

            def read_json(self) -> dict[str, object]:
                return {}

        with (
            patch("server.connect_db") as connect_db,
            patch("server.get_cookie_value", return_value="token"),
            patch("server.current_user", return_value={"id": 1, "role": "admin"}),
        ):
            connect_db.return_value.__enter__.return_value = object()
            server.FultonsHandler.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "POST",
                "/api/map-place-review-feedback",
                "",
            )

        self.assertEqual(sent_errors, [(HTTPStatus.BAD_REQUEST, "rows must be a list.")])

    def test_authenticated_player_server_does_not_expose_any_ops_monitor_route(self) -> None:
        import server

        sent_errors: list[tuple[HTTPStatus, str]] = []

        class DummyHandler:
            headers = {"Cookie": "fultons_session=token"}

            def send_error_json(self, status: HTTPStatus, message: str) -> None:
                sent_errors.append((status, message))

            def handle_admin(
                self,
                conn: object,
                user: object,
                method: str,
                path: str,
            ) -> None:
                server.FultonsHandler.handle_admin(self, conn, user, method, path)  # type: ignore[arg-type]

        with (
            patch("server.connect_db") as connect_db,
            patch("server.get_cookie_value", return_value="token"),
            patch(
                "server.current_user",
                return_value={"id": 1, "role": "admin", "is_moderator": 0},
            ),
        ):
            connect_db.return_value.__enter__.return_value = object()
            for path in ("/api/local/ops-monitor", "/api/admin/ops-monitor"):
                server.FultonsHandler.route_api(  # type: ignore[arg-type]
                    DummyHandler(),
                    "GET",
                    path,
                    "",
                )

        self.assertEqual(
            sent_errors,
            [
                (HTTPStatus.NOT_FOUND, "API route not found."),
                (HTTPStatus.NOT_FOUND, "Admin route not found."),
            ],
        )
        self.assertFalse(hasattr(server, "ops_monitor"))

    def test_internal_regenerate_daily_quiz_question_requires_valid_token(self) -> None:
        import server

        sent_errors: list[tuple[HTTPStatus, str]] = []

        class DummyHandler:
            headers = {"Authorization": "Bearer wrong-token"}

            def send_error_json(self, status: HTTPStatus, message: str) -> None:
                sent_errors.append((status, message))

        with patch("server.DAILY_QUIZ_CONFIG", SimpleNamespace(internal_token="expected-token")):
            server.FultonsHandler.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "POST",
                "/internal/regenerate-daily-quiz-question",
                "",
            )

        self.assertEqual(sent_errors, [(HTTPStatus.UNAUTHORIZED, "Invalid internal token.")])

    def test_internal_generate_daily_quiz_rejects_string_force_flag(self) -> None:
        import server

        sent_errors: list[tuple[HTTPStatus, str]] = []

        class DummyHandler:
            headers = {"Authorization": "Bearer expected-token"}

            def client_ip(self) -> str:
                return "127.0.0.1"

            def read_json(self) -> dict[str, object]:
                return {"date": "2026-06-03", "force": "false"}

            def send_error_json(self, status: HTTPStatus, message: str) -> None:
                sent_errors.append((status, message))

        with (
            patch("server.DAILY_QUIZ_CONFIG", SimpleNamespace(internal_token="expected-token")),
            patch("server.daily_quiz.generate_daily_quiz") as generate_daily_quiz,
        ):
            server.FultonsHandler.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "POST",
                "/internal/generate-daily-quiz",
                "",
            )

        self.assertEqual(
            sent_errors,
            [(HTTPStatus.BAD_REQUEST, "force must be a JSON boolean.")],
        )
        generate_daily_quiz.assert_not_called()

    def test_public_daily_quiz_route_rejects_non_current_dates(self) -> None:
        import server

        class DummyHandler:
            headers = {"Cookie": "fultons_session=token"}

            def __init__(self) -> None:
                self.errors: list[tuple[HTTPStatus, str]] = []

            def send_error_json(self, status: HTTPStatus, message: str) -> None:
                self.errors.append((status, message))

            def send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
                raise AssertionError(f"Unexpected playable payload: {status} {payload}")

        for requested_date in ("2026-06-22", "2026-06-24", "not-a-date"):
            with self.subTest(requested_date=requested_date):
                handler = DummyHandler()
                with (
                    patch("server.connect_db") as connect_db,
                    patch("server.get_cookie_value", return_value="token"),
                    patch("server.current_user", return_value={"id": 1, "role": "user"}),
                    patch("server.today_game_date", return_value="2026-06-23"),
                    patch("server.daily_quiz.quiz_payload") as quiz_payload,
                ):
                    connect_db.return_value.__enter__.return_value = object()
                    server.FultonsHandler.route_api(  # type: ignore[arg-type]
                        handler,
                        "GET",
                        "/api/daily-quiz",
                        f"date={requested_date}",
                    )

                self.assertEqual(handler.errors[0][0], HTTPStatus.NOT_FOUND)
                quiz_payload.assert_not_called()

    def test_public_daily_quiz_locks_content_before_serializing_it(self) -> None:
        import server

        calls: list[str] = []
        sent: list[tuple[HTTPStatus, dict[str, object]]] = []

        class DummyHandler:
            headers = {"Cookie": "fultons_session=token"}

            def send_error_json(self, status: HTTPStatus, message: str) -> None:
                raise AssertionError(f"unexpected API error {status}: {message}")

            def send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
                sent.append((status, payload))

        conn = object()
        with (
            patch("server.connect_db") as connect_db,
            patch("server.get_cookie_value", return_value="token"),
            patch("server.current_user", return_value={"id": 1, "role": "user"}),
            patch("server.today_game_date", return_value="2026-06-23"),
            patch("server.daily_quiz_player_state", return_value={"results": {}, "progress": {}}),
            patch(
                "server.daily_quiz.lock_published_quiz_for_play",
                side_effect=lambda *_: calls.append("lock"),
            ),
            patch(
                "server.daily_quiz.quiz_payload",
                side_effect=lambda *_: calls.append("payload")
                or {"date": "2026-06-23", "status": "published", "questions": []},
            ),
        ):
            connect_db.return_value.__enter__.return_value = conn
            server.FultonsHandler.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "GET",
                "/api/daily-quiz",
                "",
            )

        self.assertEqual(calls, ["lock", "payload"])
        self.assertEqual(sent[0][0], HTTPStatus.OK)

    def test_internal_regenerate_daily_quiz_question_returns_payload(self) -> None:
        import server

        sent: list[tuple[HTTPStatus, dict[str, object]]] = []

        class DummyHandler:
            headers = {"Authorization": "Bearer expected-token"}

            def client_ip(self) -> str:
                return "127.0.0.1"

            def read_json(self) -> dict[str, object]:
                return {
                    "date": "2026-06-03",
                    "subject": "football",
                    "difficulty": "easy",
                }

            def send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
                sent.append((status, payload))

        published = {
            "date": "2026-06-03",
            "status": "published",
            "questions": [],
        }
        status_only = {
            "date": "2026-06-03",
            "status": "published",
            "accepted_questions": 6,
            "failed_attempts": 0,
            "failure_reason": None,
        }
        with (
            patch("server.DAILY_QUIZ_CONFIG", SimpleNamespace(internal_token="expected-token")),
            patch("server.connect_db") as connect_db,
            patch("server.daily_quiz.regenerate_question", return_value=status_only) as regenerate,
            patch(
                "server.daily_quiz.quiz_questions_payload",
                return_value=published,
            ) as quiz_payload,
            patch("server.record_audit_event") as audit,
        ):
            connect_db.return_value.__enter__.return_value = object()
            server.FultonsHandler.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "POST",
                "/internal/regenerate-daily-quiz-question",
                "",
            )

        self.assertEqual(sent, [(HTTPStatus.OK, published)])
        regenerate.assert_called_once()
        quiz_payload.assert_called_once_with(connect_db.return_value.__enter__.return_value, "2026-06-03")
        audit.assert_called_once()

    def test_ops_quiz_preview_includes_saved_questions_while_generating(self) -> None:
        import daily_quiz
        import server

        with closing(sqlite3.connect(":memory:")) as conn:
            conn.row_factory = sqlite3.Row
            daily_quiz.initialize_database(conn)
            quiz_set = daily_quiz.get_or_create_quiz_set(conn, "2026-06-24")
            daily_quiz.save_question(
                conn,
                quiz_set_id=quiz_set["id"],
                question={
                    "subject": "football",
                    "difficulty": "easy",
                    "question": "Who is the question for?",
                    "choices": ["A", "B", "C", "D"],
                    "correct_answer": "A",
                    "explanation": "This is a sufficiently long explanation for the preview payload.",
                    "interesting_reason": "This question is distinctive enough for the test.",
                    "tags": ["football", "test-slot"],
                },
            )
            daily_quiz.set_quiz_status(conn, "2026-06-24", "generating")

            preview = server.ops_quiz_preview(conn, "2026-06-24")

        self.assertEqual(preview["status"], "generating")
        self.assertEqual(preview["acceptedQuestions"], 1)
        self.assertEqual(len(preview["questions"]), 1)
        self.assertEqual(preview["questions"][0]["subject"], "football")

    def test_internal_ops_summary_route_returns_payload(self) -> None:
        import server

        sent: list[tuple[HTTPStatus, dict[str, object]]] = []

        class DummyHandler:
            headers = {"Authorization": "Bearer expected-token"}

            def send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
                sent.append((status, payload))

        summary = {"ok": True, "transport": "https-fallback"}
        with (
            patch("server.DAILY_QUIZ_CONFIG", SimpleNamespace(internal_token="expected-token")),
            patch("server.internal_ops_summary_payload", return_value=summary) as internal_ops_summary,
        ):
            server.FultonsHandler.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "GET",
                "/internal/ops-summary",
                "",
            )

        self.assertEqual(sent, [(HTTPStatus.OK, summary)])
        internal_ops_summary.assert_called_once_with()

    def test_ops_map_readiness_skips_off_days_but_flags_missing_scheduled_rounds(self) -> None:
        import server

        friday = server.ops_map_readiness_test("today_map", "2026-10-02", "Today map", {"status": "missing"})
        self.assertEqual(friday["status"], "pass")
        self.assertIn("Not scheduled", friday["detail"])

        saturday_missing = server.ops_map_readiness_test("tomorrow_map", "2026-10-03", "Tomorrow map", {"status": "missing"})
        self.assertEqual(saturday_missing["status"], "fail")

        saturday_ready = server.ops_map_readiness_test("tomorrow_map", "2026-10-03", "Tomorrow map", {"status": "published", "acceptedLevels": 1})
        self.assertEqual(saturday_ready["status"], "pass")
        self.assertIn("published / accepted 1", saturday_ready["detail"])

        wednesday_missing = server.ops_map_readiness_test("today_map", "2026-10-07", "Today map", {"status": "missing"})
        self.assertEqual(wednesday_missing["status"], "fail")

    def test_local_generate_quiz_action_uses_https_not_ssh(self) -> None:
        import ops_monitor

        config = ops_monitor.MonitorConfig(
            enabled=True,
            cache_ttl_sec=15,
            ssh_target="ste@192.168.0.15",
            ssh_port=22,
            ssh_key_path="C:/Users/tester/.ssh/codex_fultons_ed25519",
            ssh_connect_timeout_sec=6,
            public_health_url="https://example.com/api/health",
            internal_base_url="https://example.com",
            internal_quiz_token="secret-token",
            compose_file="/compose.yaml",
            env_file="/app.env",
            data_dir="/data",
            db_path="/data/fultons.db",
            app_port=3000,
        )
        starting_snapshot = {
            "enabled": True,
            "status": "degraded",
            "ok": False,
            "generatedAt": "2026-06-02T12:00:00Z",
            "cacheAgeSec": 0,
            "stale": True,
            "publicProbe": {"ok": True},
            "remote": {
                "host": {"power": {"acOnline": True, "batteries": []}},
                "resources": {"memory": {}, "disks": []},
                "docker": {"containers": [], "volumes": [], "networks": []},
                "application": {
                    "health": {"ok": True},
                    "sqlite": {"tomorrowQuiz": {"date": "2026-06-03", "status": "missing"}},
                },
                "quiz": {"today": None, "tomorrow": {"date": "2026-06-03", "status": "missing"}},
                "tests": [],
                "errors": [],
            },
            "alerts": ["Tomorrow quiz is missing."],
            "errors": ["ssh timeout"],
        }
        generated = {
            "ok": True,
            "generatedDate": "2026-06-03",
            "result": {
                "date": "2026-06-03",
                "status": "published",
                "questions": [
                    {
                        "subject": "football",
                        "difficulty": "easy",
                        "question": "Who won?",
                        "choices": ["A", "B", "C", "D"],
                        "correct_answer": "A",
                        "explanation": "Because.",
                    }
                ],
            },
            "message": "Tomorrow quiz generated for 2026-06-03.",
        }

        with (
            patch.object(ops_monitor.MonitorConfig, "from_env", return_value=config),
            patch("ops_monitor.generate_tomorrow_quiz_action", return_value=generated) as generate_action,
            patch("ops_monitor.run_remote_action") as run_remote_action,
            patch("ops_monitor.collect_dashboard_snapshot", return_value=starting_snapshot),
        ):
            response = ops_monitor.run_local_action("generate_tomorrow_quiz")

        generate_action.assert_called_once_with(config)
        run_remote_action.assert_not_called()
        self.assertEqual(response["snapshot"]["remote"]["quiz"]["tomorrow"]["status"], "published")
        self.assertEqual(
            response["snapshot"]["remote"]["quiz"]["tomorrow"]["questions"][0]["question"],
            "Who won?",
        )

    def test_local_ops_action_keeps_visible_questions_when_action_result_is_status_only(self) -> None:
        import ops_monitor

        config = ops_monitor.MonitorConfig(
            enabled=True,
            cache_ttl_sec=15,
            ssh_target="ste@192.168.0.15",
            ssh_port=22,
            ssh_key_path="C:/Users/tester/.ssh/codex_fultons_ed25519",
            ssh_connect_timeout_sec=6,
            public_health_url="https://example.com/api/health",
            internal_base_url="https://example.com",
            internal_quiz_token="secret-token",
            compose_file="/compose.yaml",
            env_file="/app.env",
            data_dir="/data",
            db_path="/data/fultons.db",
            app_port=3000,
        )
        starting_snapshot = {
            "enabled": True,
            "status": "healthy",
            "ok": False,
            "generatedAt": "2026-06-23T12:00:00Z",
            "cacheAgeSec": 0,
            "stale": False,
            "publicProbe": {"ok": True},
            "remote": {
                "host": {"power": {"acOnline": True, "batteries": []}},
                "resources": {"memory": {}, "disks": []},
                "docker": {"containers": [], "volumes": [], "networks": []},
                "application": {
                    "health": {"ok": True},
                    "sqlite": {
                        "tomorrowQuiz": {
                            "date": "2026-06-24",
                            "status": "generating",
                            "acceptedQuestions": 3,
                            "failedAttempts": 12,
                            "questions": [
                                {
                                    "subject": "football",
                                    "difficulty": "easy",
                                    "question": "Existing question?",
                                    "choices": ["A", "B", "C", "D"],
                                    "correctAnswer": "A",
                                    "explanation": "Because.",
                                }
                            ],
                        }
                    },
                },
                "quiz": {
                    "today": None,
                    "tomorrow": {
                        "date": "2026-06-24",
                        "status": "generating",
                        "acceptedQuestions": 3,
                        "failedAttempts": 12,
                        "questions": [
                            {
                                "subject": "football",
                                "difficulty": "easy",
                                "question": "Existing question?",
                                "choices": ["A", "B", "C", "D"],
                                "correctAnswer": "A",
                                "explanation": "Because.",
                            }
                        ],
                    },
                },
                "tests": [],
                "errors": [],
            },
            "alerts": ["Tomorrow quiz is generating with 3/6 approved questions."],
            "errors": [],
        }
        generated = {
            "ok": True,
            "generatedDate": "2026-06-24",
            "result": {
                "date": "2026-06-24",
                "status": "generating",
                "accepted_questions": 3,
                "failed_attempts": 12,
            },
            "message": "Tomorrow quiz generation is still running for 2026-06-24; 3/6 approved so far.",
        }

        with (
            patch.object(ops_monitor.MonitorConfig, "from_env", return_value=config),
            patch("ops_monitor.generate_tomorrow_quiz_action", return_value=generated),
            patch("ops_monitor.collect_dashboard_snapshot", return_value=starting_snapshot),
        ):
            response = ops_monitor.run_local_action("generate_tomorrow_quiz")

        preview = response["snapshot"]["remote"]["quiz"]["tomorrow"]
        self.assertEqual(preview["acceptedQuestions"], 3)
        self.assertEqual(len(preview["questions"]), 1)
        self.assertEqual(preview["questions"][0]["question"], "Existing question?")

    def test_local_generate_quiz_action_updates_today_snapshot_when_today_is_missing(self) -> None:
        import ops_monitor

        config = ops_monitor.MonitorConfig(
            enabled=True,
            cache_ttl_sec=15,
            ssh_target="ste@192.168.0.15",
            ssh_port=22,
            ssh_key_path="C:/Users/tester/.ssh/codex_fultons_ed25519",
            ssh_connect_timeout_sec=6,
            public_health_url="https://example.com/api/health",
            internal_base_url="https://example.com",
            internal_quiz_token="secret-token",
            compose_file="/compose.yaml",
            env_file="/app.env",
            data_dir="/data",
            db_path="/data/fultons.db",
            app_port=3000,
        )
        starting_snapshot = {
            "enabled": True,
            "status": "degraded",
            "ok": False,
            "generatedAt": "2026-06-24T08:00:00Z",
            "cacheAgeSec": 0,
            "stale": False,
            "publicProbe": {"ok": True},
            "remote": {
                "host": {"power": {"acOnline": True, "batteries": []}},
                "resources": {"memory": {}, "disks": []},
                "docker": {"containers": [], "volumes": [], "networks": []},
                "application": {
                    "health": {"ok": True},
                    "sqlite": {
                        "todayQuiz": {"date": "2026-06-24", "status": "missing"},
                        "tomorrowQuiz": {"date": "2026-06-25", "status": "generating"},
                    },
                },
                "quiz": {
                    "today": {"date": "2026-06-24", "status": "missing"},
                    "tomorrow": {"date": "2026-06-25", "status": "generating"},
                },
                "tests": [],
                "errors": [],
            },
            "alerts": ["Today quiz is missing."],
            "errors": [],
        }
        generated = {
            "ok": True,
            "generatedDate": "2026-06-24",
            "result": {
                "date": "2026-06-24",
                "status": "published",
                "questions": [
                    {
                        "subject": "general_knowledge",
                        "difficulty": "easy",
                        "question": "Which question was repaired?",
                        "choices": ["A", "B", "C", "D"],
                        "correct_answer": "A",
                        "explanation": "Because.",
                    }
                ],
            },
            "message": "Today quiz repair triggered for 2026-06-24.",
        }

        with (
            patch.object(ops_monitor.MonitorConfig, "from_env", return_value=config),
            patch("ops_monitor.generate_tomorrow_quiz_action", return_value=generated),
            patch("ops_monitor.collect_dashboard_snapshot", return_value=starting_snapshot),
        ):
            response = ops_monitor.run_local_action("generate_tomorrow_quiz")

        preview = response["snapshot"]["remote"]["quiz"]["today"]
        self.assertEqual(preview["status"], "published")
        self.assertEqual(preview["questions"][0]["question"], "Which question was repaired?")

    def test_generate_tomorrow_quiz_action_returns_live_preview_after_timeout(self) -> None:
        import ops_monitor

        config = ops_monitor.MonitorConfig(
            enabled=True,
            cache_ttl_sec=15,
            ssh_target="",
            ssh_port=22,
            ssh_key_path="",
            ssh_connect_timeout_sec=6,
            public_health_url="https://example.com/api/health",
            internal_base_url="https://example.com",
            internal_quiz_token="secret-token",
            compose_file="/compose.yaml",
            env_file="/app.env",
            data_dir="/data",
            db_path="/data/fultons.db",
            app_port=3000,
        )

        with (
            patch(
                "ops_monitor.internal_quiz_request",
                side_effect=RuntimeError("Internal quiz request failed: The read operation timed out"),
            ),
            patch(
                "ops_monitor.current_tomorrow_quiz_preview",
                return_value={
                    "date": "2026-06-24",
                    "status": "generating",
                    "acceptedQuestions": 3,
                    "failedAttempts": 12,
                    "questions": [],
                },
            ),
        ):
            payload = ops_monitor.generate_tomorrow_quiz_action(config)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["status"], "generating")
        self.assertIn("still running", payload["message"])

    def test_collect_dashboard_snapshot_returns_https_fallback_without_waiting_for_ssh(self) -> None:
        import ops_monitor

        config = ops_monitor.MonitorConfig(
            enabled=True,
            cache_ttl_sec=15,
            ssh_target="ste@192.168.0.15",
            ssh_port=22,
            ssh_key_path="C:/Users/tester/.ssh/codex_fultons_ed25519",
            ssh_connect_timeout_sec=6,
            public_health_url="https://example.com/api/health",
            internal_base_url="https://example.com",
            internal_quiz_token="secret-token",
            compose_file="/compose.yaml",
            env_file="/app.env",
            data_dir="/data",
            db_path="/data/fultons.db",
            app_port=3000,
        )
        internal_remote = {
            "ok": True,
            "generatedAt": "2026-06-03T11:00:00Z",
            "transport": "https-fallback",
            "host": {"hostname": "fultons-quiz", "power": {"acOnline": None, "batteries": []}},
            "resources": {"memory": {}, "disks": []},
            "docker": {"containers": [], "volumes": [], "networks": []},
            "application": {
                "health": {"ok": True},
                "sqlite": {
                    "todayQuiz": None,
                    "tomorrowQuiz": {
                        "date": "2026-06-04",
                        "status": "published",
                        "acceptedQuestions": 6,
                        "failedAttempts": 0,
                        "failureReason": None,
                        "questions": [],
                    },
                },
            },
            "quiz": {
                "today": None,
                "tomorrow": {
                    "date": "2026-06-04",
                    "status": "published",
                    "acceptedQuestions": 6,
                    "failedAttempts": 0,
                    "failureReason": None,
                    "questions": [],
                },
            },
            "tests": [],
            "errors": [],
            "partial": True,
            "responseTimeMs": 42,
        }
        cache_path = Path(self.temp_dir.name) / "local-ops-snapshot.json"

        with (
            patch.object(ops_monitor.MonitorConfig, "from_env", return_value=config),
            patch.object(ops_monitor, "CACHE_FILE_PATH", cache_path),
            patch.object(ops_monitor, "_CACHED_SNAPSHOT", None),
            patch.object(ops_monitor, "_CACHED_AT_MONOTONIC", 0.0),
            patch("ops_monitor.probe_public_health", return_value={"ok": True}),
            patch("ops_monitor.collect_remote_snapshot_via_internal_api", return_value=internal_remote),
            patch("ops_monitor.schedule_background_ssh_refresh", return_value=True) as schedule_refresh,
            patch("ops_monitor.collect_remote_snapshot") as collect_remote_snapshot,
        ):
            payload = ops_monitor.collect_dashboard_snapshot(force=True)

        schedule_refresh.assert_called_once()
        collect_remote_snapshot.assert_not_called()
        self.assertFalse(payload["stale"])
        self.assertEqual(payload["status"], "degraded")
        self.assertTrue(payload["hostRefreshInProgress"])
        self.assertEqual(payload["remote"]["quiz"]["tomorrow"]["status"], "published")
        self.assertIn("HTTPS fallback", " ".join(payload["alerts"]))

    def test_collect_dashboard_snapshot_uses_recent_full_cache_without_fallback_alert(self) -> None:
        import ops_monitor

        config = ops_monitor.MonitorConfig(
            enabled=True,
            cache_ttl_sec=15,
            ssh_target="ste@192.168.0.15",
            ssh_port=22,
            ssh_key_path="C:/Users/tester/.ssh/codex_fultons_ed25519",
            ssh_connect_timeout_sec=6,
            public_health_url="https://example.com/api/health",
            internal_base_url="https://example.com",
            internal_quiz_token="secret-token",
            compose_file="/compose.yaml",
            env_file="/app.env",
            data_dir="/data",
            db_path="/data/fultons.db",
            app_port=3000,
        )
        cached_remote = {
            "ok": True,
            "generatedAt": "2026-06-05T10:50:39Z",
            "host": {"hostname": "homeserver", "power": {"acOnline": None, "batteries": []}},
            "resources": {"memory": {}, "disks": []},
            "docker": {"containers": [{"name": "fultons-quiz"}], "volumes": [], "networks": [{"name": "proxy"}]},
            "application": {"health": {"ok": True}, "sqlite": {"todayQuiz": None, "tomorrowQuiz": None}},
            "quiz": {"today": None, "tomorrow": {"date": "2026-06-06", "status": "published", "acceptedQuestions": 6, "failedAttempts": 0, "failureReason": None, "questions": []}},
            "tests": [],
            "errors": [],
            "responseTimeMs": 41,
        }
        cached_snapshot = {
            "enabled": True,
            "generatedAt": "2026-06-05T10:50:39Z",
            "publicProbe": {"ok": True},
            "remote": cached_remote,
            "alerts": [],
            "errors": [],
            "status": "healthy",
            "ok": True,
        }
        internal_remote = {
            "ok": True,
            "generatedAt": "2026-06-05T10:50:45Z",
            "transport": "https-fallback",
            "host": {"hostname": "homeserver", "power": {"acOnline": None, "batteries": []}},
            "resources": {"memory": {}, "disks": []},
            "docker": {"containers": [], "volumes": [], "networks": []},
            "application": {
                "health": {"ok": True},
                "sqlite": {
                    "todayQuiz": None,
                    "tomorrowQuiz": {
                        "date": "2026-06-06",
                        "status": "published",
                        "acceptedQuestions": 6,
                        "failedAttempts": 0,
                        "failureReason": None,
                        "questions": [],
                    },
                },
            },
            "quiz": {
                "today": None,
                "tomorrow": {
                    "date": "2026-06-06",
                    "status": "published",
                    "acceptedQuestions": 6,
                    "failedAttempts": 0,
                    "failureReason": None,
                    "questions": [],
                },
            },
            "tests": [],
            "errors": [],
            "partial": True,
            "responseTimeMs": 15,
        }
        fake_now = 1000.0
        cached_at = fake_now - 16.0

        with (
            patch.object(ops_monitor.MonitorConfig, "from_env", return_value=config),
            patch.object(ops_monitor, "CACHE_FILE_PATH", Path(self.temp_dir.name) / "ops-cache.json"),
            patch.object(ops_monitor, "_CACHED_SNAPSHOT", cached_snapshot),
            patch.object(ops_monitor, "_CACHED_AT_MONOTONIC", cached_at),
            patch("ops_monitor.probe_public_health", return_value={"ok": True}),
            patch("ops_monitor.collect_remote_snapshot_via_internal_api", return_value=internal_remote),
            patch("ops_monitor.schedule_background_ssh_refresh", return_value=True),
            patch("ops_monitor.time.monotonic", return_value=fake_now),
            patch("ops_monitor.datetime") as mocked_datetime,
        ):
            mocked_datetime.now.return_value = datetime(2026, 6, 5, 10, 50, 50, tzinfo=timezone.utc)
            mocked_datetime.fromisoformat.side_effect = datetime.fromisoformat
            payload = ops_monitor.collect_dashboard_snapshot(force=False)

        self.assertFalse(payload["stale"])
        self.assertEqual(payload["status"], "healthy")
        self.assertFalse(payload["remote"]["partial"])
        self.assertEqual(payload["remote"]["transport"], "hybrid-cache")
        self.assertEqual(payload["remote"]["docker"]["containers"][0]["name"], "fultons-quiz")
        self.assertFalse(any("HTTPS fallback" in alert for alert in payload["alerts"]))

    def test_collect_dashboard_snapshot_loads_persisted_cache_when_live_paths_fail(self) -> None:
        import ops_monitor

        cache_path = Path(self.temp_dir.name) / "local-ops-snapshot.json"
        cached_snapshot = {
            "enabled": True,
            "generatedAt": "2026-06-03T11:00:00Z",
            "publicProbe": {"ok": True},
            "remote": {
                "ok": True,
                "generatedAt": "2026-06-03T11:00:00Z",
                "application": {"health": {"ok": True}, "sqlite": {}},
                "docker": {"containers": [], "volumes": [], "networks": []},
                "errors": [],
                "host": {"hostname": "homeserver", "power": {"acOnline": None, "batteries": []}},
                "quiz": {
                    "today": None,
                    "tomorrow": {
                        "date": "2026-06-04",
                        "status": "published",
                        "acceptedQuestions": 6,
                        "failedAttempts": 0,
                        "failureReason": None,
                        "questions": [],
                    },
                },
                "resources": {"memory": {}, "disks": []},
                "responseTimeMs": 50,
                "tests": [],
            },
            "alerts": [],
            "errors": [],
            "status": "healthy",
            "ok": True,
        }
        cache_path.write_text(json.dumps(ops_monitor.snapshot_cache_payload(cached_snapshot)), encoding="utf-8")

        config = ops_monitor.MonitorConfig(
            enabled=True,
            cache_ttl_sec=15,
            ssh_target="",
            ssh_port=22,
            ssh_key_path="",
            ssh_connect_timeout_sec=6,
            public_health_url="https://example.com/api/health",
            internal_base_url="https://example.com",
            internal_quiz_token="secret-token",
            compose_file="/compose.yaml",
            env_file="/app.env",
            data_dir="/data",
            db_path="/data/fultons.db",
            app_port=3000,
        )

        with (
            patch.object(ops_monitor.MonitorConfig, "from_env", return_value=config),
            patch.object(ops_monitor, "CACHE_FILE_PATH", cache_path),
            patch.object(ops_monitor, "_CACHED_SNAPSHOT", None),
            patch.object(ops_monitor, "_CACHED_AT_MONOTONIC", 0.0),
            patch("ops_monitor.probe_public_health", return_value={"ok": True}),
            patch(
                "ops_monitor.collect_remote_snapshot_via_internal_api",
                side_effect=RuntimeError("Remote HTTPS summary endpoint is not live on the server yet."),
            ),
            patch("ops_monitor.schedule_background_ssh_refresh", return_value=False),
        ):
            payload = ops_monitor.collect_dashboard_snapshot(force=True)

        self.assertTrue(payload["stale"])
        self.assertEqual(payload["lastError"], "Remote HTTPS summary endpoint is not live on the server yet.")
        self.assertEqual(payload["remote"]["quiz"]["tomorrow"]["status"], "published")
        self.assertGreaterEqual(payload["cacheAgeSec"], 0)



    def test_production_permissions_policy_allows_geolocation(self) -> None:
        import server

        sent_headers: list[tuple[str, str]] = []

        class DummyHandler:
            def send_header(self, name: str, value: str) -> None:
                sent_headers.append((name, value))

        server.FultonsHandler.send_security_headers(DummyHandler())  # type: ignore[arg-type]

        policy_headers = [
            value for name, value in sent_headers if name.lower() == "permissions-policy"
        ]
        self.assertEqual(policy_headers, ["camera=(), microphone=(), geolocation=(self)"])

    def test_static_app_shell_disables_cache(self) -> None:
        import server

        sent_headers: list[tuple[str, str]] = []

        class DummyHandler:
            path = "/wordle"

            def send_header(self, name: str, value: str) -> None:
                sent_headers.append((name, value))

        server.FultonsHandler.send_static_cache_headers(DummyHandler())  # type: ignore[arg-type]

        self.assertIn(("Cache-Control", "no-store, max-age=0"), sent_headers)
        self.assertIn(("Pragma", "no-cache"), sent_headers)
        self.assertIn(("Expires", "0"), sent_headers)

    def test_static_media_advertises_byte_range_support(self) -> None:
        import server

        sent_headers: list[tuple[str, str]] = []

        class DummyHandler:
            path = "/videos/map-game-promo-vertical.mp4"

            def send_header(self, name: str, value: str) -> None:
                sent_headers.append((name, value))

        server.FultonsHandler.send_static_cache_headers(DummyHandler())  # type: ignore[arg-type]

        self.assertIn(("Accept-Ranges", "bytes"), sent_headers)

    def test_static_byte_ranges_support_fixed_open_and_suffix_requests(self) -> None:
        import server

        self.assertEqual(server.parse_static_byte_range("bytes=2-5", 10), (2, 5))
        self.assertEqual(server.parse_static_byte_range("bytes=7-", 10), (7, 9))
        self.assertEqual(server.parse_static_byte_range("bytes=-4", 10), (6, 9))
        self.assertEqual(server.parse_static_byte_range("bytes=8-20", 10), (8, 9))

        for invalid in ("bytes=-0", "bytes=10-", "bytes=6-2", "bytes=0-1,4-5"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    server.parse_static_byte_range(invalid, 10)

    def test_static_range_copy_stops_at_requested_length(self) -> None:
        import server

        source = BytesIO(b"0123456789")
        source.seek(3)
        output = BytesIO()

        class DummyHandler:
            _static_range_remaining = 4

        handler = DummyHandler()
        server.FultonsHandler.copyfile(handler, source, output)  # type: ignore[arg-type]

        self.assertEqual(output.getvalue(), b"3456")
        self.assertIsNone(handler._static_range_remaining)

    def test_static_hashed_assets_are_immutable(self) -> None:
        import server

        sent_headers: list[tuple[str, str]] = []
        original_dist_dir = server.DIST_DIR
        dist_dir = Path(self.temp_dir.name) / "dist"
        assets_dir = dist_dir / "assets"
        assets_dir.mkdir(parents=True)
        (assets_dir / "index-BY5qEWa0.js").write_text("console.log('new')", encoding="utf-8")

        class DummyHandler:
            path = "/assets/index-BY5qEWa0.js"

            def send_header(self, name: str, value: str) -> None:
                sent_headers.append((name, value))

        try:
            server.DIST_DIR = dist_dir
            server.FultonsHandler.send_static_cache_headers(DummyHandler())  # type: ignore[arg-type]
        finally:
            server.DIST_DIR = original_dist_dir

        self.assertEqual(
            [value for name, value in sent_headers if name == "Cache-Control"],
            ["public, max-age=31536000, immutable"],
        )

    def test_stale_index_asset_url_maps_to_current_bundle(self) -> None:
        import server

        original_dist_dir = server.DIST_DIR
        dist_dir = Path(self.temp_dir.name) / "dist"
        assets_dir = dist_dir / "assets"
        assets_dir.mkdir(parents=True)
        current_bundle = assets_dir / "index-current.js"
        current_bundle.write_text("console.log('current')", encoding="utf-8")

        class DummyHandler:
            pass

        try:
            server.DIST_DIR = dist_dir
            translated = server.FultonsHandler.translate_path(  # type: ignore[arg-type]
                DummyHandler(),
                "/assets/index-old.js",
            )
        finally:
            server.DIST_DIR = original_dist_dir

        self.assertEqual(Path(translated), current_bundle)

    def test_stale_clients_receive_cache_clear_version_header(self) -> None:
        import server

        sent_headers: list[tuple[str, str]] = []

        class DummyHeaders:
            def get(self, _name: str) -> str:
                return ""

        class DummyHandler:
            headers = DummyHeaders()

            def send_header(self, name: str, value: str) -> None:
                sent_headers.append((name, value))

        with patch("server.CACHE_VERSION", "test-build"):
            server.FultonsHandler.send_cache_version_headers(DummyHandler())  # type: ignore[arg-type]

        self.assertIn(("Clear-Site-Data", '"cache"'), sent_headers)
        self.assertTrue(
            any(name == "Set-Cookie" and value.startswith("fultons_cache_version=test-build;") for name, value in sent_headers)
        )

    def test_production_database_does_not_seed_demo_users_by_default(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                count = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
            self.assertEqual(count, 0)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_runtime_storage_health_detects_missing_required_database(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name) / "missing-db"
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"

            payload = server.runtime_storage_health(
                write_check=True,
                require_existing_db=True,
            )

            self.assertFalse(payload["ok"])
            self.assertFalse(payload["dbExists"])
            self.assertTrue(
                any("Required database is missing" in error for error in payload["errors"])
            )
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_runtime_storage_health_checks_sqlite_user_count(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name) / "runtime-db"
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            payload = server.runtime_storage_health(write_check=True, min_users=1)

            self.assertFalse(payload["ok"])
            self.assertEqual(payload["quickCheck"], "ok")
            self.assertEqual(payload["userCount"], 0)
            self.assertTrue(
                any("Database user count is 0" in error for error in payload["errors"])
            )
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path






















    def test_wordle_points_curve(self) -> None:
        import server

        self.assertEqual([server.wordle_score("won", attempt) for attempt in range(1, 7)], [10, 5, 4, 3, 2, 1])
        self.assertEqual(server.wordle_score("won", 3, difficulty=4), 10)
        self.assertEqual(server.wordle_score("won", 1, difficulty=20), 48)
        self.assertEqual(server.wordle_score("lost", 6), 0)
        self.assertEqual(server.wordle_score("lost", 3, difficulty=20), 0)

    def test_wordle_guess_rejects_stale_game_date_after_midnight(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-06-23T22:59:00+00:00"
                with conn:
                    user_id = conn.execute(
                        """
                        INSERT INTO users (username, password_hash, role, created_at, updated_at)
                        VALUES ('dad', 'hash', 'user', ?, ?)
                        """,
                        (now, now),
                    ).lastrowid

                with patch("server.today_game_date", return_value="2026-06-23"):
                    old_game = server.ensure_daily_game(conn)
                    old_state = server.serialize_wordle_state(conn, user_id, old_game)

                with patch("server.today_game_date", return_value="2026-06-24"):
                    payload, status = server.submit_wordle_guess(
                        conn,
                        user_id,
                        "raise",
                        old_state["result"]["attemptsUsed"],
                        old_state["game"]["date"],
                    )

                new_day_attempts = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM wordle_guesses
                    INNER JOIN wordle_results ON wordle_results.id = wordle_guesses.result_id
                    INNER JOIN daily_wordle_games ON daily_wordle_games.id = wordle_results.game_id
                    WHERE daily_wordle_games.game_date = '2026-06-24'
                    """
                ).fetchone()[0]
                new_day_results = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM wordle_results
                    INNER JOIN daily_wordle_games ON daily_wordle_games.id = wordle_results.game_id
                    WHERE daily_wordle_games.game_date = '2026-06-24'
                    """
                ).fetchone()[0]

            self.assertEqual(status, HTTPStatus.CONFLICT)
            self.assertIn("day changed", payload["error"])
            self.assertEqual(new_day_attempts, 0)
            self.assertEqual(new_day_results, 0)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_wordle_guess_requires_canonical_expected_game_date(self) -> None:
        import server

        for expected_game_date in (None, "", "2026-6-24", "2026-02-30"):
            with self.subTest(expected_game_date=expected_game_date):
                payload, status = server.submit_wordle_guess(  # type: ignore[arg-type]
                    None,
                    1,
                    "raise",
                    0,
                    expected_game_date,
                )
                self.assertEqual(status, HTTPStatus.BAD_REQUEST)
                self.assertIn("expectedGameDate", payload["error"])

    def test_wordle_guess_date_contract_preserves_retry_idempotence(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-06-24T12:00:00+00:00"
                with conn:
                    user_id = conn.execute(
                        """
                        INSERT INTO users (username, password_hash, role, created_at, updated_at)
                        VALUES ('dad', 'hash', 'user', ?, ?)
                        """,
                        (now, now),
                    ).lastrowid

                with patch("server.today_game_date", return_value="2026-06-24"):
                    first, first_status = server.submit_wordle_guess(
                        conn,
                        user_id,
                        "raise",
                        0,
                        "2026-06-24",
                    )
                    repeated, repeated_status = server.submit_wordle_guess(
                        conn,
                        user_id,
                        "raise",
                        0,
                        "2026-06-24",
                    )

                guess_count = conn.execute("SELECT COUNT(*) FROM wordle_guesses").fetchone()[0]

            self.assertEqual(first_status, HTTPStatus.OK)
            self.assertEqual(repeated_status, HTTPStatus.OK)
            self.assertEqual(first["result"]["attemptsUsed"], 1)
            self.assertEqual(repeated["result"]["attemptsUsed"], 1)
            self.assertEqual(guess_count, 1)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_wordle_guess_handler_wires_expected_game_date(self) -> None:
        import server

        responses: list[tuple[HTTPStatus, dict[str, object]]] = []
        conn = object()

        class DummyHandler:
            def read_json(self) -> dict[str, object]:
                return {
                    "guess": "raise",
                    "expectedAttemptsUsed": 2,
                    "expectedGameDate": "2026-06-24",
                }

            def send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
                responses.append((status, payload))

        with patch.object(
            server,
            "submit_wordle_guess",
            return_value=({"ok": True}, HTTPStatus.OK),
        ) as submit:
            server.FultonsHandler.handle_wordle_guess(  # type: ignore[arg-type]
                DummyHandler(),
                conn,
                {"id": 7},
            )

        submit.assert_called_once_with(conn, 7, "raise", 2, "2026-06-24")
        self.assertEqual(responses, [(HTTPStatus.OK, {"ok": True})])

    def test_wordle_assignment_uses_streak_based_difficulty_pool(self) -> None:
        import server
        import wordle_game

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-06-24T12:00:00+00:00"
                with conn:
                    user_id = conn.execute(
                        """
                        INSERT INTO users (username, password_hash, role, created_at, updated_at)
                        VALUES ('dad', 'hash', 'user', ?, ?)
                        """,
                        (now, now),
                    ).lastrowid
                    yesterday_game_id = conn.execute(
                        """
                        INSERT INTO daily_wordle_games (game_date, secret_word, cycle, created_at)
                        VALUES ('2026-06-23', 'raise', 1, ?)
                        """,
                        (now,),
                    ).lastrowid
                    conn.execute(
                        """
                        INSERT INTO wordle_results (
                            user_id, game_id, status, attempts_used, score,
                            completed_at, created_at, updated_at
                        )
                        VALUES (?, ?, 'won', 3, 4, ?, ?, ?)
                        """,
                        (user_id, yesterday_game_id, now, now, now),
                    )
                    today_game_id = conn.execute(
                        """
                        INSERT INTO daily_wordle_games (game_date, secret_word, cycle, created_at)
                        VALUES ('2026-06-24', 'saint', 1, ?)
                        """,
                        (now,),
                    ).lastrowid
                    today_game = conn.execute(
                        "SELECT * FROM daily_wordle_games WHERE id = ?",
                        (today_game_id,),
                    ).fetchone()

                with patch("server.today_game_date", return_value="2026-06-24"):
                    state = server.serialize_wordle_state(conn, user_id, today_game)

                assignment = conn.execute(
                    """
                    SELECT secret_word, difficulty
                    FROM wordle_user_assignments
                    WHERE user_id = ? AND game_id = ?
                    """,
                    (user_id, today_game_id),
                ).fetchone()

            self.assertEqual(state["game"]["difficulty"], 2)
            self.assertEqual(state["stats"]["currentSolveStreak"], 1)
            self.assertEqual(state["stats"]["bestSolveStreak"], 1)
            self.assertEqual(assignment["difficulty"], 2)
            self.assertIn(
                assignment["secret_word"],
                set(wordle_game.answer_words_by_difficulty()[2]),
            )
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_wordle_assignment_keeps_level_after_skipped_wordle_days(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-06-24T12:00:00+00:00"
                with conn:
                    user_id = conn.execute(
                        """
                        INSERT INTO users (username, password_hash, role, created_at, updated_at)
                        VALUES ('dad', 'hash', 'user', ?, ?)
                        """,
                        (now, now),
                    ).lastrowid
                    for game_date in ("2026-06-20", "2026-06-21"):
                        game_id = conn.execute(
                            """
                            INSERT INTO daily_wordle_games (game_date, secret_word, cycle, created_at)
                            VALUES (?, 'raise', 1, ?)
                            """,
                            (game_date, now),
                        ).lastrowid
                        conn.execute(
                            """
                            INSERT INTO wordle_results (
                                user_id, game_id, status, attempts_used, score,
                                completed_at, created_at, updated_at
                            )
                            VALUES (?, ?, 'won', 3, 4, ?, ?, ?)
                            """,
                            (user_id, game_id, now, now, now),
                        )
                    today_game_id = conn.execute(
                        """
                        INSERT INTO daily_wordle_games (game_date, secret_word, cycle, created_at)
                        VALUES ('2026-06-24', 'saint', 1, ?)
                        """,
                        (now,),
                    ).lastrowid
                    today_game = conn.execute(
                        "SELECT * FROM daily_wordle_games WHERE id = ?",
                        (today_game_id,),
                    ).fetchone()

                with patch("server.today_game_date", return_value="2026-06-24"):
                    state = server.serialize_wordle_state(conn, user_id, today_game)

                assignment = conn.execute(
                    """
                    SELECT difficulty
                    FROM wordle_user_assignments
                    WHERE user_id = ? AND game_id = ?
                    """,
                    (user_id, today_game_id),
                ).fetchone()

            self.assertEqual(state["game"]["difficulty"], 3)
            self.assertEqual(state["stats"]["currentSolveStreak"], 0)
            self.assertEqual(state["stats"]["bestSolveStreak"], 2)
            self.assertEqual(assignment["difficulty"], 3)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_wordle_assignment_refreshes_unstarted_reset_level(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-06-24T12:00:00+00:00"
                with conn:
                    user_id = conn.execute(
                        """
                        INSERT INTO users (username, password_hash, role, created_at, updated_at)
                        VALUES ('dad', 'hash', 'user', ?, ?)
                        """,
                        (now, now),
                    ).lastrowid
                    for game_date in ("2026-06-20", "2026-06-21"):
                        game_id = conn.execute(
                            """
                            INSERT INTO daily_wordle_games (game_date, secret_word, cycle, created_at)
                            VALUES (?, 'raise', 1, ?)
                            """,
                            (game_date, now),
                        ).lastrowid
                        conn.execute(
                            """
                            INSERT INTO wordle_results (
                                user_id, game_id, status, attempts_used, score,
                                completed_at, created_at, updated_at
                            )
                            VALUES (?, ?, 'won', 3, 4, ?, ?, ?)
                            """,
                            (user_id, game_id, now, now, now),
                        )
                    today_game_id = conn.execute(
                        """
                        INSERT INTO daily_wordle_games (game_date, secret_word, cycle, created_at)
                        VALUES ('2026-06-24', 'saint', 1, ?)
                        """,
                        (now,),
                    ).lastrowid
                    conn.execute(
                        """
                        INSERT INTO wordle_user_assignments
                            (user_id, game_id, secret_word, difficulty, created_at)
                        VALUES (?, ?, 'saint', 1, ?)
                        """,
                        (user_id, today_game_id, now),
                    )
                    conn.execute(
                        """
                        INSERT INTO wordle_results (
                            user_id, game_id, status, attempts_used, score,
                            completed_at, created_at, updated_at
                        )
                        VALUES (?, ?, 'in_progress', 0, 0, NULL, ?, ?)
                        """,
                        (user_id, today_game_id, now, now),
                    )
                    today_game = conn.execute(
                        "SELECT * FROM daily_wordle_games WHERE id = ?",
                        (today_game_id,),
                    ).fetchone()

                state = server.serialize_wordle_state(conn, user_id, today_game)
                assignment = conn.execute(
                    """
                    SELECT difficulty
                    FROM wordle_user_assignments
                    WHERE user_id = ? AND game_id = ?
                    """,
                    (user_id, today_game_id),
                ).fetchone()

            self.assertEqual(state["game"]["difficulty"], 3)
            self.assertEqual(assignment["difficulty"], 3)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_wordle_assignment_preserves_legacy_secret_for_started_game(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-06-24T12:00:00+00:00"
                with conn:
                    user_id = conn.execute(
                        """
                        INSERT INTO users (username, password_hash, role, created_at, updated_at)
                        VALUES ('dad', 'hash', 'user', ?, ?)
                        """,
                        (now, now),
                    ).lastrowid
                    game_id = conn.execute(
                        """
                        INSERT INTO daily_wordle_games (game_date, secret_word, cycle, created_at)
                        VALUES ('2026-06-24', 'aahed', 1, ?)
                        """,
                        (now,),
                    ).lastrowid
                    conn.execute(
                        """
                        INSERT INTO wordle_results (
                            user_id, game_id, status, attempts_used, score,
                            completed_at, created_at, updated_at
                        )
                        VALUES (?, ?, 'in_progress', 1, 0, NULL, ?, ?)
                        """,
                        (user_id, game_id, now, now),
                    )
                    game = conn.execute(
                        "SELECT * FROM daily_wordle_games WHERE id = ?",
                        (game_id,),
                    ).fetchone()

                with patch("server.today_game_date", return_value="2026-06-24"):
                    state = server.serialize_wordle_state(conn, user_id, game)

                assignment = conn.execute(
                    """
                    SELECT secret_word, difficulty
                    FROM wordle_user_assignments
                    WHERE user_id = ? AND game_id = ?
                    """,
                    (user_id, game_id),
                ).fetchone()

            self.assertEqual(state["game"]["difficulty"], 1)
            self.assertEqual(assignment["secret_word"], "aahed")
            self.assertEqual(assignment["difficulty"], 1)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_wordle_assignment_difficulty_backfill_uses_current_buckets(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-06-24T12:00:00+00:00"
                with conn:
                    user_id = conn.execute(
                        """
                        INSERT INTO users (username, password_hash, role, created_at, updated_at)
                        VALUES ('dad', 'hash', 'user', ?, ?)
                        """,
                        (now, now),
                    ).lastrowid
                    game_id = conn.execute(
                        """
                        INSERT INTO daily_wordle_games (game_date, secret_word, cycle, created_at)
                        VALUES ('2026-06-24', 'laden', 1, ?)
                        """,
                        (now,),
                    ).lastrowid
                    assignment_id = conn.execute(
                        """
                        INSERT INTO wordle_user_assignments
                            (user_id, game_id, secret_word, difficulty, created_at)
                        VALUES (?, ?, 'laden', 4, ?)
                        """,
                        (user_id, game_id, now),
                    ).lastrowid

                with conn:
                    server.backfill_wordle_assignment_difficulties(conn)

                row = conn.execute(
                    "SELECT difficulty FROM wordle_user_assignments WHERE id = ?",
                    (assignment_id,),
                ).fetchone()

            self.assertEqual(row["difficulty"], 1)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_wordle_stats_reset_current_solve_streak_after_loss(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-05-20T12:00:00+00:00"
                with conn:
                    user_id = conn.execute(
                        """
                        INSERT INTO users (username, password_hash, role, created_at, updated_at)
                        VALUES ('dad', 'hash', 'user', ?, ?)
                        """,
                        (now, now),
                    ).lastrowid
                    for game_date, status in (
                        ("2026-05-18", "won"),
                        ("2026-05-19", "won"),
                        ("2026-05-20", "lost"),
                    ):
                        game_id = conn.execute(
                            """
                            INSERT INTO daily_wordle_games (game_date, secret_word, cycle, created_at)
                            VALUES (?, 'saint', 1, ?)
                            """,
                            (game_date, now),
                        ).lastrowid
                        attempts_used = 3 if status == "won" else 6
                        score = 4 if status == "won" else 0
                        conn.execute(
                            """
                            INSERT INTO wordle_results (
                                user_id, game_id, status, attempts_used, score,
                                completed_at, created_at, updated_at
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (user_id, game_id, status, attempts_used, score, now, now, now),
                        )

                with patch("server.today_game_date", return_value="2026-05-20"):
                    stats = server.wordle_stats(conn, user_id)
                    level_progress = server.user_wordle_level_progress(conn, user_id)

            self.assertEqual(stats["currentSolveStreak"], 0)
            self.assertEqual(stats["bestSolveStreak"], 2)
            self.assertEqual(level_progress["current"], 0)
            self.assertEqual(level_progress["best"], 2)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_word_definition_uses_dictionary_api_definitions(self) -> None:
        import server

        class DictionaryResponse:
            def __enter__(self) -> "DictionaryResponse":
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def read(self, _limit: int) -> bytes:
                return json.dumps(
                    [
                        {
                            "meanings": [
                                {
                                    "partOfSpeech": "noun",
                                    "definitions": [
                                        {"definition": "A person acknowledged as holy."},
                                        {"definition": "A very good or patient person."},
                                    ],
                                }
                            ]
                        }
                    ]
                ).encode("utf-8")

        server.WORD_DEFINITION_CACHE.clear()
        self.addCleanup(server.WORD_DEFINITION_CACHE.clear)
        with patch("server.urlopen", return_value=DictionaryResponse()) as urlopen:
            result = server.word_definition("Saint")

        self.assertEqual(result["word"], "saint")
        self.assertEqual(result["partOfSpeech"], "noun")
        self.assertEqual(result["definition"], "A person acknowledged as holy.")
        self.assertEqual(
            result["definitions"],
            [
                {"definition": "A person acknowledged as holy.", "partOfSpeech": "noun"},
                {"definition": "A very good or patient person.", "partOfSpeech": "noun"},
            ],
        )
        urlopen.assert_called_once()

    def test_word_definition_uses_wiktionary_when_dictionary_api_misses(self) -> None:
        import server

        payload = {
            "parse": {
                "wikitext": (
                    "==English==\n"
                    "===Noun===\n"
                    "# [[A]] person officially recognised as [[holy]].\n"
                    "==French==\n"
                    "===Noun===\n"
                    "# saint\n"
                )
            }
        }

        server.WORD_DEFINITION_CACHE.clear()
        self.addCleanup(server.WORD_DEFINITION_CACHE.clear)
        with (
            patch("server.word_definition_from_dictionary_api", return_value=None),
            patch("server.fetch_json_url", return_value=payload),
        ):
            result = server.word_definition("Saint")

        self.assertEqual(result["word"], "saint")
        self.assertEqual(result["partOfSpeech"], "noun")
        self.assertEqual(result["definition"], "A person officially recognised as holy.")
        self.assertEqual(
            result["definitions"],
            [
                {
                    "definition": "A person officially recognised as holy.",
                    "partOfSpeech": "noun",
                }
            ],
        )
        self.assertEqual(result["sourceUrl"], "https://en.wiktionary.org/wiki/saint")

    def test_word_definition_uses_scots_wiktionary_section(self) -> None:
        import server

        payload = {
            "parse": {
                "wikitext": (
                    "==Scots==\n"
                    "===Noun===\n"
                    "# [[oil]]\n"
                    "==French==\n"
                    "===Noun===\n"
                    "# huile\n"
                )
            }
        }

        server.WORD_DEFINITION_CACHE.clear()
        self.addCleanup(server.WORD_DEFINITION_CACHE.clear)
        with (
            patch("server.word_definition_from_dictionary_api", return_value=None),
            patch("server.fetch_json_url", return_value=payload),
        ):
            result = server.word_definition("Ulzie")

        self.assertEqual(result["word"], "ulzie")
        self.assertEqual(result["partOfSpeech"], "noun")
        self.assertEqual(result["definition"], "oil")
        self.assertEqual(result["sourceUrl"], "https://en.wiktionary.org/wiki/ulzie")

    def test_quiz_scoring_adds_perfect_round_bonus_from_adjudications(self) -> None:
        import server

        questions = [
            {"difficulty": "easy", "correct_answer": "A"},
            {"difficulty": "medium", "correct_answer": "B"},
            {"difficulty": "hard", "correct_answer": "C"},
        ]

        self.assertEqual(
            server.score_quiz_adjudications(
                questions,
                [{"correct": True}, {"correct": True}, {"correct": True}],
            ),
            {"score": 12, "maxScore": 12, "correctCount": 3, "bonusPoints": 3},
        )
        self.assertEqual(
            server.score_quiz_adjudications(
                questions,
                [{"correct": True}, {"correct": False}, {"correct": True}],
            ),
            {"score": 6, "maxScore": 12, "correctCount": 2, "bonusPoints": 0},
        )

    def test_quiz_adjudication_rejects_answer_text_and_cross_question_ids(self) -> None:
        import server

        questions = [
            {
                "id": 41,
                "subject": "football",
                "difficulty": "easy",
                "question": "First?",
                "choices": ["A", "B", "C", "D"],
                "correct_answer": "A",
                "explanation": "First explanation.",
            },
            {
                "id": 42,
                "subject": "football",
                "difficulty": "medium",
                "question": "Second?",
                "choices": ["E", "F", "G", "H"],
                "correct_answer": "F",
                "explanation": "Second explanation.",
            },
        ]

        with self.assertRaisesRegex(ValueError, "question and choice IDs"):
            server.adjudicate_quiz_answers(questions, ["A", "F"])
        with self.assertRaisesRegex(ValueError, "does not belong"):
            server.adjudicate_quiz_answers(
                questions,
                [
                    {
                        "questionId": server.daily_quiz.public_question_id(41),
                        "choiceId": server.daily_quiz.public_choice_id(42, 0),
                    },
                    {
                        "questionId": server.daily_quiz.public_question_id(42),
                        "choiceId": server.daily_quiz.public_choice_id(42, 1),
                    },
                ],
            )
        with self.assertRaisesRegex(ValueError, "only be answered once"):
            server.adjudicate_quiz_answers(
                questions,
                [
                    {
                        "questionId": server.daily_quiz.public_question_id(41),
                        "choiceId": server.daily_quiz.public_choice_id(41, 0),
                    },
                    {
                        "questionId": server.daily_quiz.public_question_id(41),
                        "choiceId": server.daily_quiz.public_choice_id(41, 1),
                    },
                ],
            )

    def test_daily_quiz_result_scores_once_and_updates_leaderboard(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-06-01T12:00:00+00:00"
                with conn:
                    user_id = conn.execute(
                        """
                        INSERT INTO users (username, password_hash, role, created_at, updated_at)
                        VALUES ('dad', 'hash', 'user', ?, ?)
                        """,
                        (now, now),
                    ).lastrowid
                    quiz_set_id = conn.execute(
                        """
                        INSERT INTO daily_quiz_sets (quiz_date, status, published_at)
                        VALUES ('2026-06-01', 'published', ?)
                        """,
                        (now,),
                    ).lastrowid
                    for difficulty, answer in (("easy", "A"), ("medium", "B"), ("hard", "C")):
                        conn.execute(
                            """
                            INSERT INTO daily_quiz_questions (
                                quiz_set_id, subject, difficulty, question, choices_json,
                                correct_answer, explanation, interesting_reason, tags_json,
                                normalized_question, created_at
                            )
                            VALUES (?, 'football', ?, ?, ?, ?, 'Verified.', 'Memorable.', '[]', ?, ?)
                            """,
                            (
                                quiz_set_id,
                                difficulty,
                                f"Which answer is correct for the {difficulty} football example?",
                                json.dumps([answer, "X", "Y", "Z"]),
                                answer,
                                f"football {difficulty}",
                                now,
                            ),
                        )
                with patch("server.today_game_date", return_value="2026-06-01"):
                    questions = server.quiz_category_questions(conn, "2026-06-01", "football")
                    first_answers = [
                        {
                            "questionId": server.daily_quiz.public_question_id(question["id"]),
                            "choiceId": server.daily_quiz.public_choice_id(
                                question["id"], 1 if index == 1 else 0
                            ),
                        }
                        for index, question in enumerate(questions)
                    ]
                    first, first_status = server.save_daily_quiz_result(
                        conn,
                        user_id,
                        "2026-06-01",
                        "football",
                        first_answers,
                    )
                    conn.execute(
                        """
                        UPDATE daily_quiz_questions
                        SET correct_answer = 'X', explanation = 'Content changed later.'
                        WHERE quiz_set_id = ?
                        """,
                        (quiz_set_id,),
                    )
                    repeated, repeated_status = server.save_daily_quiz_result(
                        conn,
                        user_id,
                        "2026-06-01",
                        "football",
                        ["legacy", "clients", "remain idempotent"],
                    )
                    leaderboard = server.leaderboard_payload(conn)

            self.assertEqual(first_status, HTTPStatus.CREATED)
            self.assertEqual(repeated_status, HTTPStatus.OK)
            self.assertEqual(first["result"]["score"], 6)
            self.assertEqual(first["result"]["maxScore"], 12)
            self.assertEqual(first["result"]["bonusPoints"], 0)
            self.assertEqual(first["result"]["scoringVersion"], "opaque-choice-v1")
            self.assertEqual(len(first["result"]["adjudications"]), 3)
            self.assertEqual(repeated["result"]["score"], 6)
            self.assertEqual(
                repeated["result"]["quizVersion"], first["result"]["quizVersion"]
            )
            self.assertEqual(leaderboard["players"][0]["totalPoints"], 6)
            self.assertEqual(leaderboard["players"][0]["weeklyPoints"], 6)
            self.assertEqual(leaderboard["players"][0]["quizPoints"], 6)
            self.assertEqual(leaderboard["players"][0]["weeklyQuizPoints"], 6)
            self.assertEqual(leaderboard["summary"]["quizPlays"], 1)
            self.assertEqual(leaderboard["summary"]["periodStart"], "2026-05-26")
            self.assertEqual(leaderboard["summary"]["periodEnd"], "2026-06-01")
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_database_startup_never_regrades_legacy_quiz_results(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()
            now = "2026-06-01T12:00:00+00:00"
            with closing(server.connect_db()) as conn, conn:
                user_id = conn.execute(
                    """
                    INSERT INTO users (username, password_hash, role, created_at, updated_at)
                    VALUES ('legacy-player', 'hash', 'user', ?, ?)
                    """,
                    (now, now),
                ).lastrowid
                quiz_set_id = conn.execute(
                    """
                    INSERT INTO daily_quiz_sets (quiz_date, status, published_at)
                    VALUES ('2026-06-01', 'published', ?)
                    """,
                    (now,),
                ).lastrowid
                for difficulty, answer in (("easy", "A"), ("medium", "B"), ("hard", "C")):
                    conn.execute(
                        """
                        INSERT INTO daily_quiz_questions (
                            quiz_set_id, subject, difficulty, question, choices_json,
                            correct_answer, explanation, interesting_reason, tags_json,
                            normalized_question, created_at
                        )
                        VALUES (?, 'football', ?, ?, ?, ?, 'Verified.', 'Memorable.', '[]', ?, ?)
                        """,
                        (
                            quiz_set_id,
                            difficulty,
                            f"Legacy {difficulty}?",
                            json.dumps([answer, "X", "Y", "Z"]),
                            answer,
                            f"legacy {difficulty}",
                            now,
                        ),
                    )
                conn.execute(
                    """
                    INSERT INTO daily_quiz_results (
                        user_id, game_date, category, answers_json, score, max_score,
                        correct_count, bonus_points, completed_at, created_at, updated_at
                    ) VALUES (?, '2026-06-01', 'football', '["A","B","C"]', 4, 9, 1, 0, ?, ?, ?)
                    """,
                    (user_id, now, now, now),
                )

            server.initialize_database()
            with closing(server.connect_db()) as conn:
                row = conn.execute(
                    """
                    SELECT score, max_score, correct_count, bonus_points,
                           quiz_version, scoring_version, adjudication_json
                    FROM daily_quiz_results
                    """
                ).fetchone()

            self.assertEqual(tuple(row[:4]), (4, 9, 1, 0))
            self.assertEqual(row["quiz_version"], "legacy")
            self.assertEqual(row["scoring_version"], "legacy")
            self.assertEqual(json.loads(row["adjudication_json"]), [])
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_daily_map_guess_updates_leaderboard_map_points(self) -> None:
        import daily_map_game
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-08-11T12:00:00+00:00"
                with conn:
                    user_id = conn.execute(
                        """
                        INSERT INTO users (username, password_hash, role, created_at, updated_at)
                        VALUES ('dad', 'hash', 'user', ?, ?)
                        """,
                        (now, now),
                    ).lastrowid
                    puzzle = daily_map_game.get_or_create_puzzle(conn, "2026-08-11")
                    place = conn.execute(
                        "SELECT * FROM map_place_pool WHERE canonical_name = 'Cairo'"
                    ).fetchone()
                    self.assertIsNotNone(place)
                    config = daily_map_game.SCORE_CONFIG[place["difficulty"]]
                    level_id = conn.execute(
                        """
                        INSERT INTO daily_map_levels (
                            puzzle_id, level_slug, place_id, max_points, lambda_km, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            puzzle["id"],
                            place["difficulty"],
                            place["id"],
                            config["max_points"],
                            config["lambda_km"],
                            now,
                        ),
                    ).lastrowid
                    daily_map_game.set_puzzle_status(conn, "2026-08-11", "published")
                    selection, selection_status = daily_map_game.snap_guess(
                        conn,
                        user_id=user_id,
                        level_id=level_id,
                        lat=place["lat"],
                        lng=place["lng"],
                        today="2026-08-11",
                        allow_reverse_geocode=False,
                    )
                    self.assertEqual(selection_status, HTTPStatus.OK)
                    with patch("daily_map_game.utc_now", return_value=now):
                        result, status = daily_map_game.submit_guess(
                            conn,
                            user_id=user_id,
                            level_id=level_id,
                            selection_id=selection["selectionId"],
                            today="2026-08-11",
                        )
                    self.assertEqual(status, HTTPStatus.CREATED)
                    self.assertEqual(result["result"]["score"], 10)

                with patch("server.today_game_date", return_value="2026-08-11"):
                    leaderboard = server.leaderboard_payload(conn)

            player = leaderboard["players"][0]
            self.assertEqual(player["username"], "dad")
            self.assertEqual(player["mapPoints"], 10)
            self.assertEqual(player["weeklyMapPoints"], 10)
            self.assertEqual(player["mapPlayed"], 1)
            self.assertEqual(player["totalPoints"], 10)
            self.assertEqual(player["weeklyPoints"], 10)
            self.assertEqual(leaderboard["summary"]["mapPlays"], 1)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_daily_map_weekly_points_use_guess_completion_date(self) -> None:
        import daily_map_game
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-08-11T12:00:00+00:00"
                with conn:
                    user_id = conn.execute(
                        """
                        INSERT INTO users (username, password_hash, role, created_at, updated_at)
                        VALUES ('dad', 'hash', 'user', ?, ?)
                        """,
                        (now, now),
                    ).lastrowid
                    puzzle = daily_map_game.get_or_create_puzzle(conn, "2026-08-04")
                    place = conn.execute(
                        "SELECT * FROM map_place_pool WHERE canonical_name = 'Cairo'"
                    ).fetchone()
                    self.assertIsNotNone(place)
                    config = daily_map_game.SCORE_CONFIG[place["difficulty"]]
                    level_id = conn.execute(
                        """
                        INSERT INTO daily_map_levels (
                            puzzle_id, level_slug, place_id, max_points, lambda_km, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            puzzle["id"],
                            place["difficulty"],
                            place["id"],
                            config["max_points"],
                            config["lambda_km"],
                            now,
                        ),
                    ).lastrowid
                    daily_map_game.set_puzzle_status(conn, "2026-08-04", "published")
                    selection, selection_status = daily_map_game.snap_guess(
                        conn,
                        user_id=user_id,
                        level_id=level_id,
                        lat=place["lat"],
                        lng=place["lng"],
                        today="2026-08-04",
                        allow_reverse_geocode=False,
                    )
                    self.assertEqual(selection_status, HTTPStatus.OK)
                    with patch("daily_map_game.utc_now", return_value=now):
                        result, status = daily_map_game.submit_guess(
                            conn,
                            user_id=user_id,
                            level_id=level_id,
                            selection_id=selection["selectionId"],
                            today="2026-08-04",
                        )
                    self.assertEqual(status, HTTPStatus.CREATED)
                    self.assertEqual(result["result"]["score"], 10)

                with patch("server.today_game_date", return_value="2026-08-11"):
                    leaderboard = server.leaderboard_payload(conn)

            player = leaderboard["players"][0]
            self.assertEqual(player["mapPoints"], 10)
            self.assertEqual(player["weeklyMapPoints"], 10)
            self.assertEqual(player["weeklyPoints"], 10)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_daily_map_weekly_points_use_london_midnight_across_bst_end(self) -> None:
        import server

        class LondonBstEnd2026(tzinfo):
            """Minimal London zone for the explicit 2026 BST-end boundary under test."""

            transition = datetime(2026, 10, 25, 2)

            def utcoffset(self, value: datetime | None) -> timedelta:
                if value is not None and value.replace(tzinfo=None) < self.transition:
                    return timedelta(hours=1)
                return timedelta(0)

            def dst(self, value: datetime | None) -> timedelta:
                return self.utcoffset(value)

            def tzname(self, value: datetime | None) -> str:
                return "BST" if self.dst(value) else "GMT"

        london_timezone = LondonBstEnd2026()

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-10-24T23:30:00+00:00"
                with conn:
                    user_id = conn.execute(
                        """
                        INSERT INTO users (username, password_hash, role, created_at, updated_at)
                        VALUES ('dad', 'hash', 'user', ?, ?)
                        """,
                        (now, now),
                    ).lastrowid
                    place_id = conn.execute(
                        "SELECT id FROM map_place_pool ORDER BY id LIMIT 1"
                    ).fetchone()["id"]
                    puzzle_id = conn.execute(
                        """
                        INSERT INTO daily_map_puzzles (
                            puzzle_date, status, generated_at, published_at
                        ) VALUES ('2026-10-25', 'published', ?, ?)
                        """,
                        (now, now),
                    ).lastrowid
                    level_id = conn.execute(
                        """
                        INSERT INTO daily_map_levels (
                            puzzle_id, level_slug, place_id, max_points, lambda_km, created_at
                        ) VALUES (?, 'easy', ?, 10, 1.0, ?)
                        """,
                        (puzzle_id, place_id, now),
                    ).lastrowid
                    conn.execute(
                        """
                        INSERT INTO daily_map_guesses (
                            user_id, level_id, guessed_lat, guessed_lng, selected_name,
                            revealed_hint_count, distance_m, score, band, completed_at,
                            created_at, updated_at
                        ) VALUES (?, ?, 0, 0, NULL, 0, 0, 10, 'Solved', ?, ?, ?)
                        """,
                        (user_id, level_id, now, now, now),
                    )

                with (
                    patch.object(server, "SERVER_TZ", london_timezone),
                    patch("server.today_game_date", return_value="2026-10-31"),
                ):
                    bounds = server.game_date_period_utc_bounds(
                        "2026-10-25",
                        "2026-10-31",
                    )
                    leaderboard = server.leaderboard_payload(conn)

            self.assertEqual(
                bounds,
                (
                    "2026-10-24T23:00:00+00:00",
                    "2026-11-01T00:00:00+00:00",
                ),
            )
            self.assertEqual(leaderboard["summary"]["periodStart"], "2026-10-25")
            self.assertEqual(leaderboard["players"][0]["weeklyMapPoints"], 10)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_leaderboard_weekly_points_exclude_future_dates_for_all_games(self) -> None:
        import server

        london_timezone = timezone(timedelta(hours=1), "BST")

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-06-02T12:00:00+00:00"
                with conn:
                    user_id = conn.execute(
                        """
                        INSERT INTO users (username, password_hash, role, created_at, updated_at)
                        VALUES ('dad', 'hash', 'user', ?, ?)
                        """,
                        (now, now),
                    ).lastrowid

                    for game_date in ("2026-06-02", "2026-06-03"):
                        game_id = conn.execute(
                            """
                            INSERT INTO daily_wordle_games (
                                game_date, secret_word, cycle, created_at
                            ) VALUES (?, 'raise', 1, ?)
                            """,
                            (game_date, now),
                        ).lastrowid
                        conn.execute(
                            """
                            INSERT INTO wordle_results (
                                user_id, game_id, status, attempts_used, score,
                                completed_at, created_at, updated_at
                            ) VALUES (?, ?, 'won', 3, 4, ?, ?, ?)
                            """,
                            (user_id, game_id, now, now, now),
                        )
                        conn.execute(
                            """
                            INSERT INTO daily_quiz_results (
                                user_id, game_date, category, answers_json, score, max_score,
                                correct_count, bonus_points, completed_at, created_at, updated_at
                            ) VALUES (?, ?, 'football', '[]', 6, 12, 2, 0, ?, ?, ?)
                            """,
                            (user_id, game_date, now, now, now),
                        )

                    place_id = conn.execute(
                        "SELECT id FROM map_place_pool ORDER BY id LIMIT 1"
                    ).fetchone()["id"]
                    puzzle_id = conn.execute(
                        """
                        INSERT INTO daily_map_puzzles (
                            puzzle_date, status, generated_at, published_at
                        ) VALUES ('2026-06-02', 'published', ?, ?)
                        """,
                        (now, now),
                    ).lastrowid
                    for level_slug, completed_at in (
                        ("easy", "2026-06-02T12:00:00+00:00"),
                        ("medium", "2026-06-02T23:00:00+00:00"),
                    ):
                        level_id = conn.execute(
                            """
                            INSERT INTO daily_map_levels (
                                puzzle_id, level_slug, place_id, max_points,
                                lambda_km, created_at
                            ) VALUES (?, ?, ?, 10, 1.0, ?)
                            """,
                            (puzzle_id, level_slug, place_id, now),
                        ).lastrowid
                        conn.execute(
                            """
                            INSERT INTO daily_map_guesses (
                                user_id, level_id, guessed_lat, guessed_lng, selected_name,
                                revealed_hint_count, distance_m, score, band, completed_at,
                                created_at, updated_at
                            ) VALUES (?, ?, 0, 0, NULL, 0, 0, 10, 'Solved', ?, ?, ?)
                            """,
                            (user_id, level_id, completed_at, completed_at, completed_at),
                        )

                with (
                    patch.object(server, "SERVER_TZ", london_timezone),
                    patch("server.today_game_date", return_value="2026-06-02"),
                ):
                    leaderboard = server.leaderboard_payload(conn)

            player = leaderboard["players"][0]
            self.assertEqual(player["weeklyWordlePoints"], 4)
            self.assertEqual(player["weeklyQuizPoints"], 6)
            self.assertEqual(player["weeklyMapPoints"], 10)
            self.assertEqual(player["weeklyPoints"], 20)
            self.assertEqual(player["wordlePoints"], 8)
            self.assertEqual(player["quizPoints"], 12)
            self.assertEqual(player["mapPoints"], 20)
            self.assertEqual(player["totalPoints"], 40)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_leaderboard_includes_admin_accounts(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-05-22T12:00:00+00:00"
                with conn:
                    conn.execute(
                        "INSERT INTO users (username, password_hash, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                        ("admin", "hash", "admin", now, now),
                    )
                    conn.execute(
                        "INSERT INTO users (username, password_hash, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                        ("dad", "hash", "user", now, now),
                    )
                    rows = conn.execute("SELECT id, username FROM users").fetchall()
                    user_ids = {row["username"]: row["id"] for row in rows}
                    game_id = conn.execute(
                        """
                        INSERT INTO daily_wordle_games (game_date, secret_word, cycle, created_at)
                        VALUES ('2026-05-22', 'saint', 1, ?)
                        """,
                        (now,),
                    ).lastrowid
                    for username, score in (("admin", 9), ("dad", 6)):
                        conn.execute(
                            """
                            INSERT INTO wordle_results (
                                user_id, game_id, status, attempts_used, score,
                                completed_at, created_at, updated_at
                            )
                            VALUES (?, ?, 'won', 1, ?, ?, ?, ?)
                            """,
                            (user_ids[username], game_id, score, now, now, now),
                        )
                payload = server.leaderboard_payload(conn)

            self.assertEqual(
                [player["username"] for player in payload["players"]],
                ["admin", "dad"],
            )
            self.assertEqual([player["totalPoints"] for player in payload["players"]], [9, 6])
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_leaderboard_ranks_recent_points_above_historic_points(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-06-02T12:00:00+00:00"
                with conn:
                    for username in ("dad", "mum"):
                        conn.execute(
                            "INSERT INTO users (username, password_hash, role, created_at, updated_at) VALUES (?, 'hash', 'user', ?, ?)",
                            (username, now, now),
                        )
                    user_ids = {
                        row["username"]: row["id"]
                        for row in conn.execute("SELECT id, username FROM users").fetchall()
                    }
                    for username, game_date, score in (
                        ("dad", "2026-05-01", 10),
                        ("mum", "2026-06-02", 1),
                    ):
                        game_id = conn.execute(
                            """
                            INSERT INTO daily_wordle_games (game_date, secret_word, cycle, created_at)
                            VALUES (?, 'saint', 1, ?)
                            """,
                            (game_date, now),
                        ).lastrowid
                        conn.execute(
                            """
                            INSERT INTO wordle_results (
                                user_id, game_id, status, attempts_used, score,
                                completed_at, created_at, updated_at
                            )
                            VALUES (?, ?, 'won', 1, ?, ?, ?, ?)
                            """,
                            (user_ids[username], game_id, score, now, now, now),
                        )
                with patch("server.today_game_date", return_value="2026-06-02"):
                    payload = server.leaderboard_payload(conn)

            self.assertEqual([player["username"] for player in payload["players"]], ["mum", "dad"])
            self.assertEqual([player["weeklyPoints"] for player in payload["players"]], [1, 0])
            self.assertEqual([player["totalPoints"] for player in payload["players"]], [1, 10])
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_leaderboard_includes_wordle_difficulty_bonus(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-06-02T12:00:00+00:00"
                with conn:
                    user_id = conn.execute(
                        """
                        INSERT INTO users (username, password_hash, role, created_at, updated_at)
                        VALUES ('dad', 'hash', 'user', ?, ?)
                        """,
                        (now, now),
                    ).lastrowid
                    game_id = conn.execute(
                        """
                        INSERT INTO daily_wordle_games (game_date, secret_word, cycle, created_at)
                        VALUES ('2026-06-02', 'saint', 1, ?)
                        """,
                        (now,),
                    ).lastrowid
                    conn.execute(
                        """
                        INSERT INTO wordle_user_assignments
                            (user_id, game_id, secret_word, difficulty, created_at)
                        VALUES (?, ?, 'saint', 4, ?)
                        """,
                        (user_id, game_id, now),
                    )
                    conn.execute(
                        """
                        INSERT INTO wordle_results (
                            user_id, game_id, status, attempts_used, score,
                            completed_at, created_at, updated_at
                        )
                        VALUES (?, ?, 'won', 3, ?, ?, ?, ?)
                        """,
                        (user_id, game_id, server.wordle_score("won", 3, 4), now, now, now),
                    )
                with patch("server.today_game_date", return_value="2026-06-02"):
                    payload = server.leaderboard_payload(conn)

            player = payload["players"][0]
            self.assertEqual(player["wordlePoints"], 10)
            self.assertEqual(player["weeklyWordlePoints"], 10)
            self.assertEqual(player["wordleDifficultyBonus"], 6)
            self.assertEqual(player["weeklyWordleDifficultyBonus"], 6)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_leaderboard_includes_wordle_solve_streaks(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-05-22T12:00:00+00:00"
                with conn:
                    conn.execute(
                        "INSERT INTO users (username, password_hash, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                        ("dad", "hash", "user", now, now),
                    )
                    dad_id = conn.execute(
                        "SELECT id FROM users WHERE username = 'dad'"
                    ).fetchone()["id"]
                    for game_date in ("2026-05-18", "2026-05-19", "2026-05-21", "2026-05-22"):
                        game_id = conn.execute(
                            """
                            INSERT INTO daily_wordle_games (game_date, secret_word, cycle, created_at)
                            VALUES (?, 'saint', 1, ?)
                            """,
                            (game_date, now),
                        ).lastrowid
                        conn.execute(
                            """
                            INSERT INTO wordle_results (
                                user_id, game_id, status, attempts_used, score,
                                completed_at, created_at, updated_at
                            )
                            VALUES (?, ?, 'won', 6, 1, ?, ?, ?)
                            """,
                            (dad_id, game_id, now, now, now),
                        )
                with patch("server.today_game_date", return_value="2026-05-22"):
                    payload = server.leaderboard_payload(conn)

            self.assertEqual(payload["players"][0]["currentStreak"], 2)
            self.assertEqual(payload["players"][0]["bestStreak"], 2)
            self.assertEqual(payload["players"][0]["wordleLevel"], 5)
            self.assertEqual(payload["players"][0]["bestWordleLevel"], 5)
            self.assertEqual(payload["summary"]["bestStreak"], 2)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_leaderboard_streak_ignores_quiz_only_activity(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-05-22T12:00:00+00:00"
                with conn:
                    dad_id = conn.execute(
                        """
                        INSERT INTO users (username, password_hash, role, created_at, updated_at)
                        VALUES ('dad', 'hash', 'user', ?, ?)
                        """,
                        (now, now),
                    ).lastrowid
                    for game_date in ("2026-05-18", "2026-05-19"):
                        game_id = conn.execute(
                            """
                            INSERT INTO daily_wordle_games (game_date, secret_word, cycle, created_at)
                            VALUES (?, 'saint', 1, ?)
                            """,
                            (game_date, now),
                        ).lastrowid
                        conn.execute(
                            """
                            INSERT INTO wordle_results (
                                user_id, game_id, status, attempts_used, score,
                                completed_at, created_at, updated_at
                            )
                            VALUES (?, ?, 'won', 6, 1, ?, ?, ?)
                            """,
                            (dad_id, game_id, now, now, now),
                        )
                    conn.execute(
                        """
                        INSERT INTO daily_quiz_results (
                            user_id, game_date, category, answers_json, score, max_score,
                            correct_count, bonus_points, completed_at, created_at, updated_at
                        )
                        VALUES (?, '2026-05-22', 'football', '[]', 0, 12, 0, 0, ?, ?, ?)
                        """,
                        (dad_id, now, now, now),
                    )

                with patch("server.today_game_date", return_value="2026-05-22"):
                    payload = server.leaderboard_payload(conn)

            self.assertEqual(payload["players"][0]["currentStreak"], 0)
            self.assertEqual(payload["players"][0]["bestStreak"], 2)
            self.assertEqual(payload["players"][0]["wordleLevel"], 3)
            self.assertEqual(payload["players"][0]["bestWordleLevel"], 3)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_moderator_flag_exposes_mod_role_and_player_management(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                now = "2026-05-22T12:00:00+00:00"
                with conn:
                    conn.execute(
                        """
                        INSERT INTO users (
                            username, password_hash, role, is_moderator, created_at, updated_at
                        )
                        VALUES ('dad', 'hash', 'user', 1, ?, ?)
                        """,
                        (now, now),
                    )
                dad = conn.execute("SELECT * FROM users WHERE username = 'dad'").fetchone()

            self.assertEqual(server.user_payload(dad)["role"], "mod")
            self.assertTrue(server.user_can_manage_players(dad))
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_moderator_can_reach_only_player_management_admin_routes(self) -> None:
        import server

        reached: list[tuple[str, str]] = []
        denied: list[tuple[HTTPStatus, str]] = []

        class DummyHandler:
            headers = {"Cookie": "fultons_session=token"}

            def handle_admin(self, _conn: object, _user: object, method: str, path: str) -> None:
                reached.append((method, path))

            def send_error_json(self, status: HTTPStatus, message: str) -> None:
                denied.append((status, message))

        with (
            patch("server.connect_db") as connect_db,
            patch("server.get_cookie_value", return_value="token"),
            patch("server.current_user", return_value={"id": 1, "role": "user", "is_moderator": 1}),
        ):
            connect_db.return_value.__enter__.return_value = object()
            handler = DummyHandler()
            for method, path in (
                ("GET", "/api/admin/users"),
                ("POST", "/api/admin/users"),
                ("DELETE", "/api/admin/users/2"),
                ("POST", "/api/admin/users/2/reset-password"),
                ("GET", "/api/admin/product-report"),
                ("POST", "/api/admin/regenerate-question"),
            ):
                server.FultonsHandler.route_api(handler, method, path, "")  # type: ignore[arg-type]

        self.assertEqual(reached, [
            ("GET", "/api/admin/users"),
            ("POST", "/api/admin/users"),
            ("DELETE", "/api/admin/users/2"),
        ])
        self.assertEqual(denied, [
            (HTTPStatus.FORBIDDEN, "Admin access required."),
            (HTTPStatus.FORBIDDEN, "Admin access required."),
            (HTTPStatus.FORBIDDEN, "Admin access required."),
        ])

    def test_regular_player_cannot_reach_player_management(self) -> None:
        import server

        denied: list[tuple[HTTPStatus, str]] = []

        class DummyHandler:
            headers = {"Cookie": "fultons_session=token"}

            def send_error_json(self, status: HTTPStatus, message: str) -> None:
                denied.append((status, message))

            def handle_admin(self, *_args: object) -> None:
                raise AssertionError("A regular player must never reach admin handling")

        with (
            patch("server.connect_db") as connect_db,
            patch("server.get_cookie_value", return_value="token"),
            patch("server.current_user", return_value={"id": 1, "role": "user", "is_moderator": 0}),
        ):
            connect_db.return_value.__enter__.return_value = object()
            server.FultonsHandler.route_api(
                DummyHandler(), "GET", "/api/admin/users", "",  # type: ignore[arg-type]
            )

        self.assertEqual(denied, [(HTTPStatus.FORBIDDEN, "Admin access required.")])

    def test_moderator_can_remove_players_but_not_privileged_accounts(self) -> None:
        import server

        db_path = Path(self.temp_dir.name) / "moderators.db"
        with (
            patch.object(server, "DATA_DIR", db_path.parent),
            patch.object(server, "DB_PATH", db_path),
            patch.object(server, "SEED_DEMO_USERS", False),
        ):
            server.initialize_database()
            with closing(server.connect_db()) as conn, conn:
                now = server.utc_now()
                conn.executemany(
                    "INSERT INTO users (username,password_hash,role,is_moderator,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                    [
                        ("owner", "hash", "admin", 0, now, now),
                        ("helper", "hash", "user", 1, now, now),
                        ("player", "hash", "user", 0, now, now),
                    ],
                )
                rows = {row["username"]: row for row in conn.execute("SELECT * FROM users")}
                responses: list[tuple[HTTPStatus, object]] = []
                errors: list[tuple[HTTPStatus, str]] = []

                class DummyHandler:
                    def read_json(self) -> dict[str, str]:
                        return {"username": "newadmin", "password": "a-long-test-password", "role": "admin"}

                    def send_json(self, status: HTTPStatus, payload: object) -> None:
                        responses.append((status, payload))

                    def send_error_json(self, status: HTTPStatus, message: str) -> None:
                        errors.append((status, message))

                    def client_ip(self) -> str:
                        return "127.0.0.1"

                handler = DummyHandler()
                moderator = rows["helper"]
                server.FultonsHandler.handle_admin(handler, conn, moderator, "POST", "/api/admin/users")  # type: ignore[arg-type]
                server.FultonsHandler.handle_admin(handler, conn, moderator, "DELETE", f"/api/admin/users/{rows['owner']['id']}")  # type: ignore[arg-type]
                server.FultonsHandler.handle_admin(handler, conn, moderator, "DELETE", f"/api/admin/users/{rows['player']['id']}")  # type: ignore[arg-type]

                self.assertEqual([status for status, _ in errors], [HTTPStatus.FORBIDDEN, HTTPStatus.FORBIDDEN])
                self.assertEqual([status for status, _ in responses], [HTTPStatus.OK])
                self.assertIsNotNone(conn.execute("SELECT 1 FROM users WHERE id=?", (rows["owner"]["id"],)).fetchone())
                self.assertIsNone(conn.execute("SELECT 1 FROM users WHERE id=?", (rows["player"]["id"],)).fetchone())

    def test_news_classifier_does_not_mark_routine_stories_as_breaking(self) -> None:
        import server

        routine_titles = [
            "8 emerging transfer headlines as Hibs and Aberdeen eye centre backs",
            "Craig McLeish on St Mirren injury news and contract talks",
            "Premier Sports Cup group stage draw date and time confirmed",
            "Lack of goals could be Buddies' downfall in play-off clash",
            "St Mirren warm-up for their relegation play-off",
        ]

        for title in routine_titles:
            with self.subTest(title=title):
                priority, tags = server.classify_news_item(title, "", ["breaking"])
                self.assertEqual(priority, "news")
                self.assertNotIn("breaking", tags)

    def test_news_classifier_keeps_explicit_breaking_and_live_scores(self) -> None:
        import server

        breaking_priority, breaking_tags = server.classify_news_item(
            "Breaking: St Mirren appoint new manager",
            "",
            [],
        )
        live_priority, live_tags = server.classify_news_item(
            "Partick Thistle v St Mirren live score and match centre",
            "",
            [],
        )

        self.assertEqual(breaking_priority, "breaking")
        self.assertIn("breaking", breaking_tags)
        self.assertEqual(live_priority, "live-scores")
        self.assertIn("live-scores", live_tags)

    def test_news_classifier_marks_major_result_stories_as_breaking(self) -> None:
        import server

        priority, tags = server.classify_news_item(
            "St Mirren stay up after dramatic play-off win",
            "The Buddies secured Premiership survival with a priceless victory.",
            ["news"],
        )

        self.assertEqual(priority, "breaking")
        self.assertIn("breaking", tags)

    def test_news_classifier_marks_confirmed_club_change_as_breaking(self) -> None:
        import server

        priority, tags = server.classify_news_item(
            "John Park leaves St Mirren as new recruitment chief named",
            "",
            ["news"],
        )

        self.assertEqual(priority, "breaking")
        self.assertIn("breaking", tags)
        self.assertNotIn("news", tags)

    def test_news_payload_removes_source_suffix_and_repeated_summary(self) -> None:
        import server

        item = server.validate_news_payload(
            {
                "sourceKey": "bbc-story",
                "title": "St Mirren remain in talks with captain Mark O'Hara and four others - BBC",
                "url": "https://example.com/st-mirren-captain",
                "source": "BBC",
                "summary": "St Mirren remain in talks with captain Mark O'Hara and four others BBC",
                "publishedAt": "2026-06-01T08:05:47+00:00",
                "tags": ["st-mirren"],
            }
        )

        self.assertEqual(
            item["title"],
            "St Mirren remain in talks with captain Mark O'Hara and four others",
        )
        self.assertEqual(item["summary"], "")
        self.assertTrue(item["story_key"])

    def test_news_duplicate_match_accepts_same_story_headline_rewrite(self) -> None:
        import server

        self.assertTrue(
            server.news_titles_are_near_duplicates(
                "Connor Ronan targeted for Aberdeen transfer as Stephen Robinson eyes reunion",
                "Connor Ronan an Aberdeen transfer target as Stephen Robinson eyes St Mirren reunion at Pittodrie",
            )
        )
        self.assertFalse(
            server.news_titles_are_near_duplicates(
                "St Mirren remain in talks with captain Mark O'Hara and four others",
                "Premier Sports Cup group stage fixtures and TV selections",
            )
        )

    def test_news_upsert_collapses_google_url_variants_for_same_story(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            base_payload = {
                "title": "John Park leaves St Mirren as new recruitment chief named - The Herald",
                "source": "The Herald",
                "summary": "John Park leaves St Mirren as new recruitment chief named The Herald",
                "publishedAt": "2026-05-31T18:49:43+00:00",
                "tags": ["st-mirren", "scottish-football"],
            }
            with closing(server.connect_db()) as conn:
                with conn:
                    first, first_inserted = server.upsert_news_item(
                        conn,
                        {
                            **base_payload,
                            "sourceKey": "google-variant-one",
                            "url": "https://news.google.com/rss/articles/one?oc=5",
                        },
                    )
                    second, second_inserted = server.upsert_news_item(
                        conn,
                        {
                            **base_payload,
                            "sourceKey": "google-variant-two",
                            "url": "https://news.google.com/rss/articles/two?oc=5",
                        },
                    )
                count = conn.execute("SELECT COUNT(*) FROM news_items").fetchone()[0]

            self.assertTrue(first_inserted)
            self.assertFalse(second_inserted)
            self.assertEqual(first["id"], second["id"])
            self.assertEqual(second["summary"], "")
            self.assertEqual(second["priority"], "breaking")
            self.assertEqual(count, 1)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_news_backfill_removes_existing_duplicate_rows(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            now = "2026-06-01T10:00:00+00:00"
            with closing(server.connect_db()) as conn:
                with conn:
                    for source_key, url in (
                        ("variant-one", "https://news.google.com/rss/articles/one"),
                        ("variant-two", "https://news.google.com/rss/articles/two"),
                    ):
                        conn.execute(
                            """
                            INSERT INTO news_items (
                                source_key, story_key, kind, title, url, source, summary,
                                published_at, host, priority, tags_json, created_at, updated_at
                            )
                            VALUES (?, '', 'article', ?, ?, 'BBC', ?, ?, 'news.google.com',
                                'news', '[]', ?, ?)
                            """,
                            (
                                source_key,
                                "St Mirren appoint new manager - BBC",
                                url,
                                "St Mirren appoint new manager BBC",
                                now,
                                now,
                                now,
                            ),
                        )
                    server.backfill_news_items(conn)
                rows = conn.execute("SELECT * FROM news_items").fetchall()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["title"], "St Mirren appoint new manager")
            self.assertEqual(rows[0]["summary"], "")
            self.assertEqual(rows[0]["priority"], "breaking")
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_news_backfill_rewrites_story_keys_without_unique_index_conflicts(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            now = "2026-06-01T10:00:00+00:00"
            with closing(server.connect_db()) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO news_items (
                            source_key, story_key, kind, title, url, source, summary,
                            published_at, host, priority, tags_json, created_at, updated_at
                        )
                        VALUES (?, ?, 'article', ?, ?, 'BBC', ?, ?, 'news.google.com',
                            'news', '[]', ?, ?)
                        """,
                        (
                            "story-a",
                            "story-a",
                            "St Mirren appoint new manager - BBC",
                            "https://news.google.com/rss/articles/a",
                            "St Mirren appoint new manager BBC",
                            now,
                            now,
                            now,
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO news_items (
                            source_key, story_key, kind, title, url, source, summary,
                            published_at, host, priority, tags_json, created_at, updated_at
                        )
                        VALUES (?, ?, 'article', ?, ?, 'BBC', ?, ?, 'news.google.com',
                            'news', '[]', ?, ?)
                        """,
                        (
                            "story-b",
                            "story-b",
                            "St Mirren appoint new manager | BBC",
                            "https://news.google.com/rss/articles/b",
                            "St Mirren appoint new manager BBC",
                            now,
                            now,
                            now,
                        ),
                    )
                    server.backfill_news_items(conn)
                rows = conn.execute("SELECT title, story_key FROM news_items").fetchall()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["title"], "St Mirren appoint new manager")
            self.assertTrue(rows[0]["story_key"])
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_news_feed_supplements_with_other_sports_when_recent_scoped_items_are_thin(self) -> None:
        import server

        now = datetime.now(timezone.utc).replace(microsecond=0)

        def payload(title: str, source: str, published_at: datetime, url: str, tags: list[str]) -> dict[str, object]:
            return {
                "sourceKey": url,
                "kind": "article",
                "title": title,
                "url": f"https://news.example.com/{url}",
                "source": source,
                "summary": title,
                "publishedAt": published_at.isoformat(),
                "host": "news.example.com",
                "priority": "media",
                "tags": tags,
            }

        def fake_fetch(query: str, tags: tuple[str, ...] | list[str] | None = None) -> list[dict[str, object]]:
            if query == "scoped-one":
                return [
                    payload(
                        "St Mirren end-of-season review",
                        "Club site",
                        now - timedelta(hours=96),
                        "scoped-one",
                        ["st-mirren", "scottish-football"],
                    )
                ]
            if query == "scoped-two":
                return [
                    payload(
                        "Scottish Premiership contract latest",
                        "BBC",
                        now - timedelta(hours=120),
                        "scoped-two",
                        ["st-mirren", "scottish-football"],
                    )
                ]
            if query == "snooker-fallback":
                return [
                    payload(
                        "World Snooker Tour final heads for deciding frame",
                        "Eurosport",
                        now - timedelta(hours=6),
                        "snooker-fallback",
                        ["sport", "snooker"],
                    )
                ]
            return []

        with (
            patch("server.NEWS_SCOPED_QUERY_CONFIGS", ({"query": "scoped-one", "tags": ("st-mirren",)}, {"query": "scoped-two", "tags": ("st-mirren",)})),
            patch("server.NEWS_SUPPLEMENTAL_QUERY_CONFIGS", ({"query": "snooker-fallback", "tags": ("sport", "snooker")},)),
            patch("server.NEWS_MIN_RECENT_SCOPED_ITEMS", 1),
            patch("server.fetch_news_feed", side_effect=fake_fetch),
            patch("server.safe_log"),
        ):
            items, recent_scoped_count = server.collect_news_feed_items()

        self.assertEqual(recent_scoped_count, 0)
        self.assertEqual(
            [item["title"] for item in items],
            [
                "St Mirren end-of-season review",
                "Scottish Premiership contract latest",
                "World Snooker Tour final heads for deciding frame",
            ],
        )

    def test_news_feed_skips_other_sports_when_recent_scoped_items_are_sufficient(self) -> None:
        import server

        now = datetime.now(timezone.utc).replace(microsecond=0)
        seen_queries: list[str] = []

        def payload(title: str, source: str, published_at: datetime, url: str, tags: list[str]) -> dict[str, object]:
            return {
                "sourceKey": url,
                "kind": "article",
                "title": title,
                "url": f"https://news.example.com/{url}",
                "source": source,
                "summary": title,
                "publishedAt": published_at.isoformat(),
                "host": "news.example.com",
                "priority": "media",
                "tags": tags,
            }

        def fake_fetch(query: str, tags: tuple[str, ...] | list[str] | None = None) -> list[dict[str, object]]:
            seen_queries.append(query)
            if query == "scoped-one":
                return [
                    payload(
                        "St Mirren captain discusses new deal",
                        "BBC",
                        now - timedelta(hours=4),
                        "scoped-one",
                        ["st-mirren", "scottish-football"],
                    )
                ]
            if query == "scoped-two":
                return [
                    payload(
                        "St Mirren transfer target linked again",
                        "Sky Sports",
                        now - timedelta(hours=8),
                        "scoped-two",
                        ["st-mirren", "scottish-football"],
                    )
                ]
            if query == "snooker-fallback":
                return [
                    payload(
                        "This should not be fetched",
                        "Eurosport",
                        now - timedelta(hours=2),
                        "snooker-fallback",
                        ["sport", "snooker"],
                    )
                ]
            return []

        with (
            patch("server.NEWS_SCOPED_QUERY_CONFIGS", ({"query": "scoped-one", "tags": ("st-mirren",)}, {"query": "scoped-two", "tags": ("st-mirren",)})),
            patch("server.NEWS_SUPPLEMENTAL_QUERY_CONFIGS", ({"query": "snooker-fallback", "tags": ("sport", "snooker")},)),
            patch("server.NEWS_MIN_RECENT_SCOPED_ITEMS", 2),
            patch("server.fetch_news_feed", side_effect=fake_fetch),
            patch("server.safe_log"),
        ):
            items, recent_scoped_count = server.collect_news_feed_items()

        self.assertEqual(recent_scoped_count, 2)
        self.assertEqual(
            [item["title"] for item in items],
            [
                "St Mirren captain discusses new deal",
                "St Mirren transfer target linked again",
            ],
        )
        self.assertEqual(seen_queries, ["scoped-one", "scoped-two"])

    def test_daily_quiz_scheduler_uses_next_configured_window(self) -> None:
        import server

        with (
            patch("server.server_timezone", return_value=timezone.utc),
            patch("server.DAILY_QUIZ_SCHEDULER_HOUR", 0),
            patch("server.DAILY_QUIZ_SCHEDULER_MINUTE", 5),
        ):
            before_window = server.next_daily_quiz_run(
                datetime(2026, 6, 1, 0, 4, tzinfo=timezone.utc)
            )
            after_window = server.next_daily_quiz_run(
                datetime(2026, 6, 1, 0, 6, tzinfo=timezone.utc)
            )

        self.assertEqual(before_window, datetime(2026, 6, 1, 0, 5, tzinfo=timezone.utc))
        self.assertEqual(after_window, datetime(2026, 6, 2, 0, 5, tzinfo=timezone.utc))

    def test_daily_quiz_recovery_mode_starts_at_8pm_uk_time(self) -> None:
        import server

        target = "2026-08-12"
        with patch(
            "server.server_timezone", return_value=timezone(timedelta(hours=1))
        ):
            before = server.daily_quiz_generation_mode(
                target,
                datetime(2026, 8, 11, 18, 59, tzinfo=timezone.utc),
            )
            at_threshold = server.daily_quiz_generation_mode(
                target,
                datetime(2026, 8, 11, 19, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(before, "normal")
        self.assertEqual(at_threshold, "recovery")

    def test_missing_today_quiz_always_uses_recovery_mode(self) -> None:
        import server

        with patch(
            "server.server_timezone", return_value=timezone(timedelta(hours=1))
        ):
            mode = server.daily_quiz_generation_mode(
                "2026-08-12",
                datetime(2026, 8, 12, 0, 30, tzinfo=timezone.utc),
            )

        self.assertEqual(mode, "recovery")

    def test_daily_quiz_scheduler_skips_already_published_tomorrow(self) -> None:
        import daily_quiz
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with closing(server.connect_db()) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO daily_quiz_sets (quiz_date, status, published_at)
                        VALUES ('2026-06-02', 'published', ?)
                        """,
                        ("2026-06-01T12:00:00+00:00",),
                    )

            with patch("daily_quiz.generate_daily_quiz") as generate_daily_quiz:
                server.ensure_tomorrow_daily_quiz(
                    datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
                )

            generate_daily_quiz.assert_not_called()
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_daily_quiz_scheduler_commits_generated_tomorrow_quiz(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            def fake_generate_daily_quiz(conn, quiz_date, config, log):
                conn.execute(
                    """
                    INSERT INTO daily_quiz_sets (quiz_date, status, published_at)
                    VALUES (?, 'published', ?)
                    """,
                    (quiz_date, "2026-06-04T00:05:00+00:00"),
                )
                return {"date": quiz_date, "status": "published"}

            with patch("daily_quiz.generate_daily_quiz", side_effect=fake_generate_daily_quiz):
                server.ensure_tomorrow_daily_quiz(
                    datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
                )

            with closing(server.connect_db()) as conn:
                row = conn.execute(
                    "SELECT quiz_date, status, published_at FROM daily_quiz_sets WHERE quiz_date = ?",
                    ("2026-06-05",),
                ).fetchone()

            self.assertIsNotNone(row)
            self.assertEqual(row["quiz_date"], "2026-06-05")
            self.assertEqual(row["status"], "published")
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_daily_quiz_scheduler_repairs_today_before_generating_tomorrow(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            with patch("daily_quiz.generate_daily_quiz") as generate_daily_quiz:
                generate_daily_quiz.side_effect = [
                    {
                        "date": "2026-06-24",
                        "status": "generating",
                        "accepted_questions": 4,
                        "failed_attempts": 12,
                        "failure_reason": None,
                    }
                ]
                results = server.ensure_active_daily_quizzes(
                    datetime(2026, 6, 24, 0, 10, tzinfo=timezone.utc)
                )
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

        self.assertEqual([result["date"] for result in results], ["2026-06-24"])
        self.assertEqual(generate_daily_quiz.call_count, 1)
        self.assertEqual(generate_daily_quiz.call_args.kwargs["quiz_date"], "2026-06-24")

    def test_daily_quiz_scheduler_prefills_low_reserve_before_calling_provider(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()
            target_dates = ["2026-06-24", "2026-06-25"]
            with (
                patch("daily_quiz.generate_daily_quiz") as generate_daily_quiz,
                patch(
                    "daily_quiz.publish_verified_archive_fallback",
                    side_effect=[
                        {"date": value, "status": "published"} for value in target_dates
                    ],
                ) as archive_fallback,
            ):
                results = server.ensure_daily_quiz_dates(target_dates)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

        self.assertEqual([result["status"] for result in results], ["published", "published"])
        generate_daily_quiz.assert_not_called()
        self.assertEqual(archive_fallback.call_count, 2)

    def test_daily_quiz_scheduler_claims_pool_before_archive_or_inline_ai(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name)
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()
            target_dates = ["2026-06-24", "2026-06-25"]
            with (
                patch("server.DAILY_QUIZ_POOL_ENABLED", True),
                patch(
                    "daily_quiz.publish_quiz_from_pool",
                    side_effect=[
                        {"date": value, "status": "published"} for value in target_dates
                    ],
                ) as pool_publish,
                patch("daily_quiz.publish_verified_archive_fallback") as archive_fallback,
                patch("daily_quiz.generate_daily_quiz") as generate_daily_quiz,
            ):
                results = server.ensure_daily_quiz_dates(target_dates)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

        self.assertEqual([result["status"] for result in results], ["published", "published"])
        self.assertEqual(pool_publish.call_count, 2)
        archive_fallback.assert_not_called()
        generate_daily_quiz.assert_not_called()

    def test_quiz_pool_scheduler_sleeps_until_provider_reset(self) -> None:
        import server

        now = datetime(2026, 6, 1, 0, 10, tzinfo=timezone.utc)
        reset_at = datetime(2026, 6, 1, 8, 5, tzinfo=timezone.utc)
        next_run = datetime(2026, 6, 2, 0, 5, tzinfo=timezone.utc)
        sleep_calls: list[float] = []

        def stop_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)
            raise RuntimeError("stop loop")

        with (
            patch("server.DAILY_QUIZ_POOL_ENABLED", True),
            patch("server.ensure_active_daily_quizzes", return_value=[{"status": "published"}]),
            patch(
                "server.maintain_daily_quiz_pool",
                return_value={
                    "status": "capped",
                    "ready": 0,
                    "retry_at": reset_at.isoformat(),
                },
            ),
            patch("server.next_daily_quiz_run", return_value=next_run),
            patch("server.time.sleep", side_effect=stop_sleep),
            patch("server.safe_log"),
            patch("server.datetime") as mocked_datetime,
        ):
            mocked_datetime.now.return_value = now
            mocked_datetime.fromisoformat.side_effect = datetime.fromisoformat
            with self.assertRaisesRegex(RuntimeError, "stop loop"):
                server.daily_quiz_scheduler_loop()

        self.assertEqual(sleep_calls, [(reset_at - now).total_seconds()])

    def test_daily_quiz_scheduler_retries_unpublished_tomorrow_before_next_window(self) -> None:
        import server

        now = datetime(2026, 6, 1, 0, 10, tzinfo=timezone.utc)
        next_run = datetime(2026, 6, 2, 0, 5, tzinfo=timezone.utc)
        sleep_calls: list[float] = []

        def stop_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)
            raise RuntimeError("stop loop")

        with (
            patch("server.ensure_active_daily_quizzes", return_value=[{"status": "generating"}]),
            patch("server.DAILY_QUIZ_POOL_ENABLED", False),
            patch("server.next_daily_quiz_run", return_value=next_run),
            patch("server.DAILY_QUIZ_RETRY_INTERVAL_SEC", 900),
            patch("server.time.sleep", side_effect=stop_sleep),
            patch("server.safe_log"),
            patch("server.datetime") as mocked_datetime,
        ):
            mocked_datetime.now.return_value = now
            mocked_datetime.fromisoformat.side_effect = datetime.fromisoformat
            with self.assertRaisesRegex(RuntimeError, "stop loop"):
                server.daily_quiz_scheduler_loop()

        self.assertEqual(sleep_calls, [900.0])

    def test_daily_quiz_scheduler_uses_longer_retry_after_transient_provider_failure(self) -> None:
        import server

        now = datetime(2026, 6, 1, 0, 10, tzinfo=timezone.utc)
        next_run = datetime(2026, 6, 2, 0, 5, tzinfo=timezone.utc)
        sleep_calls: list[float] = []

        def stop_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)
            raise RuntimeError("stop loop")

        with (
            patch(
                "server.ensure_active_daily_quizzes",
                return_value=[{"status": "generating", "last_failure_transient": True}],
            ),
            patch("server.DAILY_QUIZ_POOL_ENABLED", False),
            patch("server.next_daily_quiz_run", return_value=next_run),
            patch("server.DAILY_QUIZ_RETRY_INTERVAL_SEC", 900),
            patch("server.DAILY_QUIZ_TRANSIENT_RETRY_INTERVAL_SEC", 3600),
            patch("server.time.sleep", side_effect=stop_sleep),
            patch("server.safe_log"),
            patch("server.datetime") as mocked_datetime,
        ):
            mocked_datetime.now.return_value = now
            mocked_datetime.fromisoformat.side_effect = datetime.fromisoformat
            with self.assertRaisesRegex(RuntimeError, "stop loop"):
                server.daily_quiz_scheduler_loop()

        self.assertEqual(sleep_calls, [3600.0])

    def test_daily_map_scheduler_uses_longer_retry_after_transient_provider_failure(self) -> None:
        import server

        now = datetime(2026, 6, 1, 0, 10, tzinfo=timezone.utc)
        next_run = datetime(2026, 6, 2, 0, 2, tzinfo=timezone.utc)
        sleep_calls: list[float] = []

        def stop_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)
            raise RuntimeError("stop loop")

        with (
            patch(
                "server.ensure_active_daily_map_games",
                return_value=[
                    {
                        "status": "failed",
                        "failureReason": "Gemini request failed with HTTP 429.",
                    }
                ],
            ),
            patch("server.next_daily_map_game_run", return_value=next_run),
            patch("server.DAILY_MAP_GAME_RETRY_INTERVAL_SEC", 300),
            patch("server.DAILY_MAP_GAME_TRANSIENT_RETRY_INTERVAL_SEC", 3600),
            patch("server.time.sleep", side_effect=stop_sleep),
            patch("server.safe_log"),
            patch("server.datetime") as mocked_datetime,
        ):
            mocked_datetime.now.return_value = now
            mocked_datetime.fromisoformat.side_effect = datetime.fromisoformat
            with self.assertRaisesRegex(RuntimeError, "stop loop"):
                server.daily_map_game_scheduler_loop()

        self.assertEqual(sleep_calls, [3600.0])

    def test_daily_quiz_write_helpers_commit_immediately(self) -> None:
        import daily_quiz

        class DummyCursor:
            def __init__(self, row: dict[str, object] | None = None) -> None:
                self._row = row

            def fetchone(self) -> dict[str, object] | None:
                return self._row

        class DummyConnection:
            def __init__(self) -> None:
                self.in_transaction = False
                self.commit_calls = 0

            def execute(self, statement: str, _params: object = None) -> DummyCursor:
                if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                    self.in_transaction = True
                if "SELECT * FROM daily_quiz_sets" in statement:
                    return DummyCursor({"id": 1, "status": "generating"})
                return DummyCursor()

            def commit(self) -> None:
                self.commit_calls += 1
                self.in_transaction = False

        conn = DummyConnection()
        question = {
            "subject": "football",
            "difficulty": "easy",
            "question": "Who scored?",
            "choices": ["A", "B", "C", "D"],
            "correct_answer": "A",
            "explanation": "Because.",
            "interesting_reason": "Memorable.",
            "tags": ["football"],
        }

        quiz_set = daily_quiz.get_or_create_quiz_set(conn, "2026-06-05")
        daily_quiz.set_quiz_status(conn, "2026-06-05", "generating")
        daily_quiz.save_attempt(
            conn,
            quiz_date="2026-06-05",
            subject="football",
            difficulty="easy",
            attempt_number=1,
            provider="gemini",
            generated=question,
            critic=None,
            passed=False,
            failure_reason="Retry",
        )
        daily_quiz.save_question(conn, quiz_set_id=int(quiz_set["id"]), question=question)

        self.assertEqual(int(quiz_set["id"]), 1)
        self.assertEqual(conn.commit_calls, 4)
        self.assertFalse(conn.in_transaction)


    def test_daily_map_scheduler_discovers_candidates_before_clue_generation(self) -> None:
        import daily_map_game
        import server

        db_path = Path(self.temp_dir.name) / "fultons.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL)")
        daily_map_game.initialize_database(conn)
        provider = object()
        generated = {
            "place": "Fresh Stadium",
            "learning_profile_hash": "profile-hash",
            "critic_mode": "ai",
            "publish_result": {"date": "2026-07-29", "status": "published"},
        }

        with (
            patch.object(server, "DB_PATH", db_path),
            patch.object(server, "DAILY_MAP_AI_GENERATION_ENABLED", True),
            patch.object(server, "DAILY_MAP_AI_DISCOVER_COUNT", 4),
            patch.object(server, "DAILY_MAP_AI_DISCOVERY_ATTEMPTS", 2),
            patch(
                "server.map_clue_rewriter.ConfiguredMapClueProvider.from_env",
                return_value=provider,
            ),
            patch(
                "server.generate_ai_daily_map_round.discover_uncurated_candidates",
                return_value={
                    "accepted_count": 1,
                    "candidate_place_ids": [42],
                    "candidate_names": ["fresh stadium"],
                },
            ) as discover,
            patch(
                "server.generate_ai_daily_map_round.generate_round",
                return_value=generated,
            ) as generate,
        ):
            result = server.generate_daily_map_game_for_date(
                conn,
                puzzle_date="2026-07-29",
            )

        self.assertEqual(result["status"], "published")
        discover.assert_called_once_with(
            db_path=db_path,
            provider=provider,
            puzzle_date="2026-07-29",
            count=4,
            max_attempts=2,
            excluded_names=set(),
            required_place_type=None,
        )
        self.assertEqual(generate.call_args.kwargs["eligible_place_ids"], {42})
        self.assertEqual(generate.call_args.kwargs["eligible_names"], {"fresh stadium"})
        self.assertIsNone(generate.call_args.kwargs["required_place_type"])

    def test_daily_map_scheduler_discovers_fresh_batch_after_generation_rejection(self) -> None:
        import daily_map_game
        import server

        db_path = Path(self.temp_dir.name) / "fultons.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL)")
        daily_map_game.initialize_database(conn)
        provider = object()
        generated = {
            "place": "Second Stadium",
            "learning_profile_hash": "profile-hash",
            "critic_mode": "ai",
            "publish_result": {"date": "2026-07-29", "status": "published"},
        }

        with (
            patch.object(server, "DB_PATH", db_path),
            patch.object(server, "DAILY_MAP_AI_GENERATION_ENABLED", True),
            patch.object(server, "DAILY_MAP_AI_DISCOVER_COUNT", 4),
            patch.object(server, "DAILY_MAP_AI_DISCOVERY_ATTEMPTS", 2),
            patch.object(server, "DAILY_MAP_AI_GENERATION_ROUNDS", 2),
            patch(
                "server.map_clue_rewriter.ConfiguredMapClueProvider.from_env",
                return_value=provider,
            ),
            patch(
                "server.generate_ai_daily_map_round.discover_uncurated_candidates",
                side_effect=[
                    {
                        "accepted_count": 1,
                        "candidate_place_ids": [41],
                        "candidate_names": ["first stadium"],
                    },
                    {
                        "accepted_count": 1,
                        "candidate_place_ids": [42],
                        "candidate_names": ["second stadium"],
                    },
                ],
            ) as discover,
            patch(
                "server.generate_ai_daily_map_round.generate_round",
                side_effect=[LookupError("First batch failed quality gates."), generated],
            ) as generate,
        ):
            result = server.generate_daily_map_game_for_date(
                conn,
                puzzle_date="2026-07-29",
            )

        self.assertEqual(result["status"], "published")
        self.assertEqual(discover.call_count, 2)
        self.assertEqual(discover.call_args_list[0].kwargs["excluded_names"], set())
        self.assertEqual(
            discover.call_args_list[1].kwargs["excluded_names"],
            {"first stadium"},
        )
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(generate.call_args_list[0].kwargs["eligible_place_ids"], {41})
        self.assertEqual(generate.call_args_list[1].kwargs["eligible_place_ids"], {42})

    def test_daily_map_generation_reports_original_failure_after_schema_initialization(self) -> None:
        import daily_map_game
        import server

        db_path = Path(self.temp_dir.name) / "map-generation-failure.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL)")
        daily_map_game.initialize_database(conn)

        def initialize_then_fail(*_args, **_kwargs):
            daily_map_game.initialize_database(conn)
            raise LookupError("No learned hook passed.")

        with (
            patch.object(server, "DB_PATH", db_path),
            patch.object(server, "DAILY_MAP_AI_GENERATION_ENABLED", True),
            patch.object(server, "DAILY_MAP_AI_DISCOVER_COUNT", 0),
            patch(
                "server.map_clue_rewriter.ConfiguredMapClueProvider.from_env",
                return_value=object(),
            ),
            patch(
                "server.generate_ai_daily_map_round.generate_round",
                side_effect=initialize_then_fail,
            ),
        ):
            result = server.generate_daily_map_game_for_date(
                conn,
                puzzle_date="2026-08-04",
            )

        self.assertEqual(result["status"], "failed")
        self.assertIn("No learned hook passed", result["failureReason"])

    def test_daily_map_generation_publishes_reviewed_fallback_after_ai_failure(self) -> None:
        import daily_map_game
        import server
        from tools import install_map_reviewed_fallbacks

        db_path = Path(self.temp_dir.name) / "map-generation-fallback.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL)")
        daily_map_game.initialize_database(conn)
        install_map_reviewed_fallbacks.install_seed(
            conn,
            Path(__file__).resolve().parents[1]
            / "deploy"
            / "map-reviewed-fallbacks.json",
        )
        conn.commit()

        with (
            patch.object(server, "DB_PATH", db_path),
            patch.object(server, "DAILY_MAP_AI_GENERATION_ENABLED", True),
            patch.object(server, "DAILY_MAP_AI_DISCOVER_COUNT", 0),
            patch.object(server, "DAILY_MAP_STADIUM_LAUNCH_DATE", ""),
            patch(
                "server.map_clue_rewriter.ConfiguredMapClueProvider.from_env",
                return_value=object(),
            ),
            patch(
                "server.generate_ai_daily_map_round.generate_round",
                side_effect=LookupError("No learned hook passed."),
            ),
        ):
            result = server.generate_daily_map_game_for_date(
                conn,
                puzzle_date="2026-08-07",
            )

        self.assertEqual(result["status"], "published")
        published = conn.execute(
            """
            SELECT map_place_pool.canonical_name
            FROM daily_map_levels
            INNER JOIN daily_map_puzzles
                ON daily_map_puzzles.id = daily_map_levels.puzzle_id
            INNER JOIN map_place_pool
                ON map_place_pool.id = daily_map_levels.place_id
            WHERE daily_map_puzzles.puzzle_date = '2026-08-07'
            """
        ).fetchone()
        self.assertIsNotNone(published)

    def test_daily_map_prepares_two_days_ahead(self) -> None:
        import server

        now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
        with patch.object(server, "DAILY_MAP_PREPARE_DAYS_AHEAD", 2):
            dates = server.active_daily_map_game_dates(now)

        self.assertEqual(dates, ["2026-08-05", "2026-08-06", "2026-08-07"])

    def test_daily_map_launch_prefers_stadiums_for_first_three_rounds(self) -> None:
        import server

        with (
            patch.object(server, "DAILY_MAP_STADIUM_LAUNCH_DATE", "2026-08-10"),
            patch.object(server, "DAILY_MAP_STADIUM_LAUNCH_ROUNDS", 3),
        ):
            self.assertIsNone(server.daily_map_launch_preferred_place_type("2026-08-09"))
            self.assertEqual(
                server.daily_map_launch_preferred_place_type("2026-08-10"),
                "stadium",
            )
            self.assertEqual(
                server.daily_map_launch_preferred_place_type("2026-08-12"),
                "stadium",
            )
            self.assertIsNone(server.daily_map_launch_preferred_place_type("2026-08-13"))

    def test_future_map_dates_are_only_requestable_in_review_mode(self) -> None:
        import server

        with (
            patch.object(server, "today_game_date", return_value="2026-08-03"),
            patch.object(server, "DAILY_MAP_FUTURE_REVIEW_ENABLED", False),
        ):
            self.assertTrue(server.daily_map_date_is_requestable("2026-08-03"))
            self.assertFalse(server.daily_map_date_is_requestable("2026-08-04"))

        with (
            patch.object(server, "today_game_date", return_value="2026-08-03"),
            patch.object(server, "DAILY_MAP_FUTURE_REVIEW_ENABLED", True),
        ):
            self.assertTrue(server.daily_map_date_is_requestable("2026-08-04"))

    def test_future_map_review_uses_the_selected_levels_date_for_play(self) -> None:
        import daily_map_game
        import server

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL)")
        daily_map_game.initialize_database(conn)
        puzzle_id = conn.execute(
            "INSERT INTO daily_map_puzzles (puzzle_date, status) VALUES (?, 'published')",
            ("2026-08-04",),
        ).lastrowid
        place_id = conn.execute("SELECT id FROM map_place_pool LIMIT 1").fetchone()["id"]
        level_id = conn.execute(
            """
            INSERT INTO daily_map_levels (
                puzzle_id, level_slug, place_id, max_points, lambda_km, created_at
            ) VALUES (?, 'easy', ?, 10, 100, ?)
            """,
            (puzzle_id, place_id, "2026-08-03T12:00:00+00:00"),
        ).lastrowid

        with (
            patch.object(server, "today_game_date", return_value="2026-08-03"),
            patch.object(server, "DAILY_MAP_FUTURE_REVIEW_ENABLED", True),
        ):
            self.assertEqual(
                server.daily_map_submission_date(conn, level_id),
                "2026-08-04",
            )

        with (
            patch.object(server, "today_game_date", return_value="2026-08-03"),
            patch.object(server, "DAILY_MAP_FUTURE_REVIEW_ENABLED", False),
        ):
            self.assertEqual(
                server.daily_map_submission_date(conn, level_id),
                "2026-08-03",
            )


if __name__ == "__main__":
    unittest.main()

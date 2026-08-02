from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
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
        import production_server

        header = production_server.session_header("token-value")
        self.assertIn("HttpOnly", header)
        self.assertIn("SameSite=Lax", header)
        self.assertIn("Secure", header)

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

    def test_admin_ops_monitor_route_requires_admin(self) -> None:
        import server

        sent_errors: list[tuple[HTTPStatus, str]] = []

        class DummyHandler:
            headers = {"Cookie": "fultons_session=token"}

            def send_error_json(self, status: HTTPStatus, message: str) -> None:
                sent_errors.append((status, message))

        with (
            patch("server.connect_db") as connect_db,
            patch("server.get_cookie_value", return_value="token"),
            patch("server.current_user", return_value={"id": 1, "role": "mod"}),
            patch("ops_monitor.collect_dashboard_snapshot") as collect_snapshot,
        ):
            connect_db.return_value.__enter__.return_value = object()
            server.FultonsHandler.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "GET",
                "/api/admin/ops-monitor",
                "",
            )

        self.assertEqual(sent_errors, [(HTTPStatus.FORBIDDEN, "Admin access required.")])
        collect_snapshot.assert_not_called()

    def test_admin_ops_monitor_route_returns_snapshot_for_admin(self) -> None:
        import server

        sent: list[tuple[HTTPStatus, dict[str, object]]] = []

        class DummyHandler:
            headers = {"Cookie": "fultons_session=token"}

            def send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
                sent.append((status, payload))

        snapshot = {"enabled": True, "status": "healthy"}
        with (
            patch("server.connect_db") as connect_db,
            patch("server.get_cookie_value", return_value="token"),
            patch("server.current_user", return_value={"id": 1, "role": "admin"}),
            patch("ops_monitor.collect_dashboard_snapshot", return_value=snapshot) as collect_snapshot,
        ):
            connect_db.return_value.__enter__.return_value = object()
            server.FultonsHandler.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "GET",
                "/api/admin/ops-monitor",
                "force=1",
            )

        self.assertEqual(sent, [(HTTPStatus.OK, snapshot)])
        collect_snapshot.assert_called_once_with(force=True)

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

    def test_local_ops_config_route_returns_saved_settings(self) -> None:
        import server

        sent: list[tuple[HTTPStatus, dict[str, object]]] = []

        class DummyHandler:
            client_address = ("127.0.0.1", 12345)

            def send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
                sent.append((status, payload))

            def client_ip(self) -> str:
                return self.client_address[0]

            def is_loopback_request(self) -> bool:
                return server.FultonsHandler.is_loopback_request(self)  # type: ignore[arg-type]

        response = {"config": {"sshTarget": "ste@192.168.0.15"}, "settingsPath": "C:/temp.json"}
        with (
            patch("server.LOCAL_OPS_ENABLED", True),
            patch("local_ops_settings.monitor_settings_response", return_value=response),
        ):
            server.FultonsHandler.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "GET",
                "/api/local/ops-config",
                "",
            )

        self.assertEqual(sent, [(HTTPStatus.OK, response)])

    def test_local_ops_config_route_saves_settings(self) -> None:
        import server

        sent: list[tuple[HTTPStatus, dict[str, object]]] = []

        class DummyHandler:
            client_address = ("127.0.0.1", 12345)

            def read_json(self) -> dict[str, object]:
                return {"sshTarget": "ste@192.168.0.22", "sshPort": 2222}

            def send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
                sent.append((status, payload))

            def client_ip(self) -> str:
                return self.client_address[0]

            def is_loopback_request(self) -> bool:
                return server.FultonsHandler.is_loopback_request(self)  # type: ignore[arg-type]

        saved = {"sshTarget": "ste@192.168.0.22", "sshPort": 2222}
        with (
            patch("server.LOCAL_OPS_ENABLED", True),
            patch("local_ops_settings.save_monitor_settings", return_value=saved),
            patch("local_ops_settings.SETTINGS_PATH", "C:/temp.json"),
        ):
            server.FultonsHandler.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "POST",
                "/api/local/ops-config",
                "",
            )

        self.assertEqual(
            sent,
            [(HTTPStatus.OK, {"config": saved, "settingsPath": "C:/temp.json"})],
        )

    def test_local_ops_monitor_route_requires_loopback(self) -> None:
        import server

        sent_errors: list[tuple[HTTPStatus, str]] = []

        class DummyHandler:
            client_address = ("192.168.0.9", 12345)

            def send_error_json(self, status: HTTPStatus, message: str) -> None:
                sent_errors.append((status, message))

            def client_ip(self) -> str:
                return self.client_address[0]

            def is_loopback_request(self) -> bool:
                return server.FultonsHandler.is_loopback_request(self)  # type: ignore[arg-type]

        with (
            patch("server.LOCAL_OPS_ENABLED", True),
            patch("ops_monitor.collect_dashboard_snapshot") as collect_snapshot,
        ):
            server.FultonsHandler.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "GET",
                "/api/local/ops-monitor",
                "",
            )

        self.assertEqual(
            sent_errors,
            [(HTTPStatus.FORBIDDEN, "Local ops dashboard is available only from localhost.")],
        )
        collect_snapshot.assert_not_called()

    def test_local_ops_monitor_route_returns_snapshot_for_loopback(self) -> None:
        import server

        sent: list[tuple[HTTPStatus, dict[str, object]]] = []

        class DummyHandler:
            client_address = ("127.0.0.1", 12345)

            def send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
                sent.append((status, payload))

            def client_ip(self) -> str:
                return self.client_address[0]

            def is_loopback_request(self) -> bool:
                return server.FultonsHandler.is_loopback_request(self)  # type: ignore[arg-type]

        snapshot = {"enabled": True, "status": "healthy"}
        with (
            patch("server.LOCAL_OPS_ENABLED", True),
            patch("ops_monitor.collect_dashboard_snapshot", return_value=snapshot) as collect_snapshot,
        ):
            server.FultonsHandler.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "GET",
                "/api/local/ops-monitor",
                "force=1",
            )

        self.assertEqual(sent, [(HTTPStatus.OK, snapshot)])
        collect_snapshot.assert_called_once_with(force=True)

    def test_local_ops_action_route_requires_loopback(self) -> None:
        import server

        sent_errors: list[tuple[HTTPStatus, str]] = []

        class DummyHandler:
            client_address = ("192.168.0.9", 12345)

            def send_error_json(self, status: HTTPStatus, message: str) -> None:
                sent_errors.append((status, message))

            def client_ip(self) -> str:
                return self.client_address[0]

            def is_loopback_request(self) -> bool:
                return server.FultonsHandler.is_loopback_request(self)  # type: ignore[arg-type]

        with (
            patch("server.LOCAL_OPS_ENABLED", True),
            patch("ops_monitor.run_local_action") as run_local_action,
        ):
            server.FultonsHandler.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "POST",
                "/api/local/ops-action",
                "",
            )

        self.assertEqual(
            sent_errors,
            [(HTTPStatus.FORBIDDEN, "Local ops dashboard is available only from localhost.")],
        )
        run_local_action.assert_not_called()

    def test_local_ops_action_route_runs_requested_action(self) -> None:
        import server

        sent: list[tuple[HTTPStatus, dict[str, object]]] = []

        class DummyHandler:
            client_address = ("127.0.0.1", 12345)

            def read_json(self) -> dict[str, object]:
                return {"action": "remove_orphaned_networks"}

            def send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
                sent.append((status, payload))

            def client_ip(self) -> str:
                return self.client_address[0]

            def is_loopback_request(self) -> bool:
                return server.FultonsHandler.is_loopback_request(self)  # type: ignore[arg-type]

        response = {
            "action": "remove_orphaned_networks",
            "message": "Removed 2 orphaned network(s).",
            "details": {"removedNetworks": ["fultons-quiz_app"]},
            "snapshot": {"enabled": True, "status": "healthy"},
        }
        with (
            patch("server.LOCAL_OPS_ENABLED", True),
            patch("ops_monitor.run_local_action", return_value=response) as run_local_action,
        ):
            server.FultonsHandler.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "POST",
                "/api/local/ops-action",
                "",
            )

        self.assertEqual(sent, [(HTTPStatus.OK, response)])
        run_local_action.assert_called_once_with("remove_orphaned_networks", params=None)

    def test_local_ops_action_route_starts_async_job_for_regenerate_question(self) -> None:
        import server

        sent: list[tuple[HTTPStatus, dict[str, object]]] = []

        class DummyHandler:
            client_address = ("127.0.0.1", 12345)

            def read_json(self) -> dict[str, object]:
                return {
                    "action": "regenerate_question",
                    "params": {
                        "date": "2026-06-03",
                        "subject": "football",
                        "difficulty": "hard",
                    },
                }

            def send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
                sent.append((status, payload))

            def client_ip(self) -> str:
                return self.client_address[0]

            def is_loopback_request(self) -> bool:
                return server.FultonsHandler.is_loopback_request(self)  # type: ignore[arg-type]

        response = {
            "action": "regenerate_question",
            "status": "queued",
            "done": False,
            "jobId": "ops-123",
            "message": "Refreshing football / hard for 2026-06-03.",
        }
        with (
            patch("server.LOCAL_OPS_ENABLED", True),
            patch("ops_monitor.start_local_action_job", return_value=response) as start_local_action_job,
            patch("ops_monitor.run_local_action") as run_local_action,
        ):
            server.FultonsHandler.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "POST",
                "/api/local/ops-action",
                "",
            )

        self.assertEqual(sent, [(HTTPStatus.ACCEPTED, response)])
        start_local_action_job.assert_called_once_with(
            "regenerate_question",
            params={"date": "2026-06-03", "subject": "football", "difficulty": "hard"},
        )
        run_local_action.assert_not_called()

    def test_local_ops_action_status_route_returns_job(self) -> None:
        import server

        sent: list[tuple[HTTPStatus, dict[str, object]]] = []

        class DummyHandler:
            client_address = ("127.0.0.1", 12345)

            def send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
                sent.append((status, payload))

            def client_ip(self) -> str:
                return self.client_address[0]

            def is_loopback_request(self) -> bool:
                return server.FultonsHandler.is_loopback_request(self)  # type: ignore[arg-type]

        response = {
            "action": "regenerate_question",
            "status": "running",
            "done": False,
            "jobId": "ops-123",
            "message": "Refreshing football / hard for 2026-06-03.",
        }
        with (
            patch("server.LOCAL_OPS_ENABLED", True),
            patch("ops_monitor.get_local_action_job", return_value=response) as get_local_action_job,
        ):
            server.FultonsHandler.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "GET",
                "/api/local/ops-action-status",
                "jobId=ops-123",
            )

        self.assertEqual(sent, [(HTTPStatus.OK, response)])
        get_local_action_job.assert_called_once_with("ops-123")

    def test_local_ops_action_route_rejects_invalid_action(self) -> None:
        import server

        sent_errors: list[tuple[HTTPStatus, str]] = []

        class DummyHandler:
            client_address = ("127.0.0.1", 12345)

            def read_json(self) -> dict[str, object]:
                return {"action": "drop_database"}

            def send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
                raise AssertionError("send_json should not be called for invalid actions")

            def send_error_json(self, status: HTTPStatus, message: str) -> None:
                sent_errors.append((status, message))

            def client_ip(self) -> str:
                return self.client_address[0]

            def is_loopback_request(self) -> bool:
                return server.FultonsHandler.is_loopback_request(self)  # type: ignore[arg-type]

        with (
            patch("server.LOCAL_OPS_ENABLED", True),
            patch("ops_monitor.run_local_action", side_effect=ValueError("Unsupported ops action: drop_database")),
        ):
            server.FultonsHandler.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "POST",
                "/api/local/ops-action",
                "",
            )

        self.assertEqual(
            sent_errors,
            [(HTTPStatus.BAD_REQUEST, "Unsupported ops action: drop_database")],
        )

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

    def test_internal_regenerate_daily_quiz_question_returns_payload(self) -> None:
        import server

        sent: list[tuple[HTTPStatus, dict[str, object]]] = []

        class DummyHandler:
            headers = {"Authorization": "Bearer expected-token"}

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
            patch("server.daily_quiz.quiz_payload", return_value=published) as quiz_payload,
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

    def test_local_generate_quiz_action_uses_https_not_ssh(self) -> None:
        import ops_monitor

        config = ops_monitor.MonitorConfig(
            enabled=True,
            cache_ttl_sec=15,
            ssh_target="ste@192.168.0.15",
            ssh_port=22,
            ssh_key_path="C:/Users/svens/.ssh/codex_fultons_ed25519",
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
            ssh_key_path="C:/Users/svens/.ssh/codex_fultons_ed25519",
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
            ssh_key_path="C:/Users/svens/.ssh/codex_fultons_ed25519",
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
            ssh_key_path="C:/Users/svens/.ssh/codex_fultons_ed25519",
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
            ssh_key_path="C:/Users/svens/.ssh/codex_fultons_ed25519",
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

    def test_fact_image_route_requires_login(self) -> None:
        import production_server

        error: list[tuple[HTTPStatus, str]] = []

        class DummyHandler:
            headers: dict[str, str] = {}

            def send_error_json(self, status: HTTPStatus, message: str) -> None:
                error.append((status, message))

        with (
            patch("server.connect_db") as connect_db,
            patch("server.get_cookie_value", return_value=None),
            patch("server.current_user", return_value=None),
            patch("production_server.compute_fact_image") as compute_fact_image,
        ):
            connect_db.return_value.__enter__.return_value = object()
            production_server.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "POST",
                "/api/fact-image",
            )

        self.assertEqual(error, [(HTTPStatus.UNAUTHORIZED, "Login required.")])
        compute_fact_image.assert_not_called()

    def test_fact_image_route_resolves_images_for_logged_in_users(self) -> None:
        import production_server

        sent: list[tuple[HTTPStatus, dict[str, str]]] = []

        class DummyHandler:
            headers = {"Cookie": "fultons_session=token"}

            def read_json(self) -> dict[str, str]:
                return {
                    "title": "Paisley Abbey",
                    "text": "Paisley Abbey is a local landmark.",
                    "placeTitle": "Paisley",
                }

            def send_json(self, status: HTTPStatus, payload: dict[str, str]) -> None:
                sent.append((status, payload))

        image = {"url": "https://upload.wikimedia.org/paisley-abbey.jpg"}
        with (
            patch("server.connect_db") as connect_db,
            patch("server.get_cookie_value", return_value="token"),
            patch("server.current_user", return_value={"id": 1}),
            patch("production_server.compute_fact_image", return_value=image) as compute_fact_image,
        ):
            connect_db.return_value.__enter__.return_value = object()
            production_server.route_api(  # type: ignore[arg-type]
                DummyHandler(),
                "POST",
                "/api/fact-image",
            )

        self.assertEqual(sent, [(HTTPStatus.OK, image)])
        compute_fact_image.assert_called_once_with(
            "Paisley Abbey",
            "Paisley Abbey is a local landmark.",
            "Paisley",
        )

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

    def test_wikipedia_summary_prefers_paisley_town_alias(self) -> None:
        import server

        with patch("server.fetch_json_url", return_value={"title": "Paisley, Renfrewshire"}) as fetch:
            payload = server.fetch_wikipedia_summary("Paisley", "en")

        self.assertEqual(payload["title"], "Paisley, Renfrewshire")
        self.assertIn("Paisley,_Renfrewshire", fetch.call_args[0][0])

    def test_location_facts_are_themed_sourced_and_structured(self) -> None:
        import server

        summary = {
            "title": "Paisley, Renfrewshire",
            "extract": (
                "Paisley is a town in Renfrewshire, Scotland. "
                "Paisley Abbey is a medieval landmark in the town."
            ),
        }
        extract = (
            "Paisley became known for its textile industry and the Paisley pattern. "
            "The town has hosted cultural events and arts activity. "
            "Notable people from Paisley include writers, musicians and footballers. "
            "The historic centre contains important public buildings and churches."
        )
        entity = {
            "id": "Q123",
            "labels": {"en": {"value": "Paisley"}},
            "claims": {
                "P31": [
                    {"mainsnak": {"datavalue": {"value": {"numeric-id": 486972}}}},
                ],
                "P1082": [
                    {"mainsnak": {"datavalue": {"value": {"amount": "+77220"}}}},
                ],
                "P571": [
                    {"mainsnak": {"datavalue": {"value": {"time": "+1157-01-01T00:00:00Z"}}}},
                ],
                "P131": [
                    {"mainsnak": {"datavalue": {"value": {"numeric-id": 211091}}}},
                ],
            },
        }

        with patch(
            "server.fetch_wikidata_labels",
            return_value={"Q486972": "human settlement", "Q211091": "Renfrewshire"},
        ):
            profile = server.wikidata_profile(entity, "en", "Paisley")
            facts = server.build_location_facts(
                summary,
                extract,
                8,
                "https://en.wikipedia.org/wiki/Paisley,_Renfrewshire",
                entity,
                "en",
            )

        self.assertEqual(profile["population"], "77,220")
        self.assertEqual(profile["areas"], ["Renfrewshire"])
        self.assertGreaterEqual(len(facts), 6)
        self.assertTrue(all(isinstance(fact, dict) for fact in facts))
        self.assertTrue(all(fact["sourceName"] and fact["sourceUrl"] for fact in facts))
        self.assertTrue(all(fact["confidence"] in {"high", "medium", "low"} for fact in facts))
        self.assertEqual({fact["sourceName"] for fact in facts}, {"Wikipedia", "Wikidata"})
        self.assertTrue({"history", "landmark", "industry", "culture"}.intersection(
            {fact["theme"] for fact in facts}
        ))

    def test_reviewed_location_facts_generate_ai_text_and_attach_internal_critique(self) -> None:
        import server

        candidates = [
            {
                "title": "History",
                "text": "Paisley Abbey was founded in the 12th century and remains one of the town's best-known landmarks.",
                "theme": "history",
                "sourceName": "Wikipedia",
                "sourceUrl": "https://example.com/abbey",
                "confidence": "medium",
            },
            {
                "title": "Industry",
                "text": "Paisley gave its name to the Paisley pattern through the town's textile industry.",
                "theme": "industry",
                "sourceName": "Wikipedia",
                "sourceUrl": "https://example.com/pattern",
                "confidence": "medium",
            },
            {
                "title": "Culture",
                "text": "Paisley has hosted major cultural events and arts activity in its town centre.",
                "theme": "culture",
                "sourceName": "Wikipedia",
                "sourceUrl": "https://example.com/culture",
                "confidence": "medium",
            },
        ]
        selection = {
            "facts": [
                {
                    "title": "Paisley Abbey",
                    "text": "Paisley Abbey remains one of the town's defining landmarks, with roots going back to the 12th century.",
                    "theme": "history",
                    "sourceEvidenceIndex": 0,
                },
                {
                    "title": "Paisley's textile legacy",
                    "text": "Paisley's textile trade made its famous pattern known far beyond Renfrewshire.",
                    "theme": "industry",
                    "sourceEvidenceIndex": 1,
                },
            ]
        }
        critique = {
            "overallPassed": True,
            "notes": "Both facts are specific and distinctive.",
            "facts": [
                {
                    "factIndex": 0,
                    "passed": True,
                    "relevance": 10,
                    "interestingness": 8,
                    "placeSpecificity": 10,
                    "summary": "It names a landmark strongly associated with Paisley.",
                },
                {
                    "factIndex": 1,
                    "passed": True,
                    "relevance": 9,
                    "interestingness": 8,
                    "placeSpecificity": 9,
                    "summary": "It links Paisley to a distinctive export and identity marker.",
                },
            ],
        }

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name) / "runtime-db"
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()
            rotation_key = server.history_fact_rotation_key("Paisley, Renfrewshire", "en")
            evidence = [
                {
                    "title": "Paisley Abbey history",
                    "sourceName": "Paisley Abbey",
                    "sourceUrl": "https://paisleyabbey.org.uk/history",
                    "snippet": "Paisley Abbey traces its origins to the 12th century.",
                    "excerpt": "Paisley Abbey traces its origins to the 12th century and remains central to the town's story.",
                },
                {
                    "title": "Paisley Pattern",
                    "sourceName": "Renfrewshire Council",
                    "sourceUrl": "https://www.renfrewshire.gov.uk/article/12345/paisley-pattern-history",
                    "snippet": "Paisley's textile trade spread the paisley pattern widely.",
                    "excerpt": "Paisley's textile trade spread the paisley pattern far beyond Renfrewshire.",
                },
            ]

            with (
                patch("server.FACTS_GEMINI_API_KEY", "test-key"),
                patch("server.search_web_fact_evidence", return_value=evidence),
                patch("server.facts_ai_json_response", side_effect=[selection, critique]) as gemini_request,
            ):
                facts = server.reviewed_location_facts(
                    rotation_key,
                    "Paisley, Renfrewshire",
                    candidates,
                    limit=2,
                    recent_texts=["Paisley Abbey is a medieval landmark in the town."],
                )

            self.assertEqual(len(facts), 2)
            self.assertEqual(facts[0]["title"], "Paisley Abbey")
            self.assertEqual(facts[0]["sourceUrl"], "https://paisleyabbey.org.uk/history")
            self.assertEqual(facts[1]["title"], "Paisley's textile legacy")
            self.assertEqual(facts[1]["critique"]["relevance"], 9)
            self.assertIn("distinctive export", facts[1]["critique"]["summary"])
            self.assertEqual(gemini_request.call_count, 2)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_facts_ai_json_response_uses_openrouter_fallback_after_gemini_failure(self) -> None:
        import server

        fallback_payload = {
            "facts": [
                {
                    "title": "Paisley Abbey",
                    "text": "Paisley Abbey remains one of the town's defining landmarks.",
                    "theme": "history",
                    "sourceEvidenceIndex": 0,
                }
            ]
        }

        with (
            patch("server.FACTS_GEMINI_API_KEY", "test-key"),
            patch("server.FACTS_FALLBACK_PROVIDER", "openrouter"),
            patch("server.FACTS_FALLBACK_API_KEY", "fallback-key"),
            patch("server.FACTS_FALLBACK_BASE_URL", "https://openrouter.ai/api/v1"),
            patch("server.FACTS_FALLBACK_GENERATOR_MODEL", "openai/gpt-4.1-mini"),
            patch(
                "server.facts_gemini_json_response",
                side_effect=RuntimeError("Gemini request failed with HTTP 429."),
            ),
            patch(
                "server.facts_compatible_json_response",
                return_value=fallback_payload,
            ) as compatible_request,
        ):
            payload = server.facts_ai_json_response(
                task="generator",
                model=server.FACTS_AI_GENERATOR_MODEL,
                prompt="Prompt",
                schema={"type": "object"},
            )

        self.assertEqual(payload, fallback_payload)
        compatible_request.assert_called_once_with(
            provider_name="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key="fallback-key",
            model="openai/gpt-4.1-mini",
            prompt="Prompt",
            schema={"type": "object"},
        )

    def test_facts_ai_json_response_uses_second_fallback_after_first_fails(self) -> None:
        import server

        fallback_payload = {
            "facts": [
                {
                    "title": "Paisley Book Festival",
                    "text": "Paisley hosts a book festival in the town centre.",
                    "theme": "culture",
                    "sourceEvidenceIndex": 1,
                }
            ]
        }

        with (
            patch("server.FACTS_GEMINI_API_KEY", ""),
            patch("server.FACTS_FALLBACK_PROVIDER", "openrouter"),
            patch("server.FACTS_FALLBACK_API_KEY", "fallback-key"),
            patch("server.FACTS_FALLBACK_BASE_URL", "https://openrouter.ai/api/v1"),
            patch("server.FACTS_FALLBACK_GENERATOR_MODEL", "google/gemini-2.5-flash"),
            patch("server.FACTS_FALLBACK2_PROVIDER", "openrouter"),
            patch("server.FACTS_FALLBACK2_API_KEY", "fallback2-key"),
            patch("server.FACTS_FALLBACK2_BASE_URL", "https://openrouter.ai/api/v1"),
            patch("server.FACTS_FALLBACK2_GENERATOR_MODEL", "openrouter/free"),
            patch(
                "server.facts_compatible_json_response",
                side_effect=[RuntimeError("primary fallback unavailable"), fallback_payload],
            ) as compatible_request,
        ):
            payload = server.facts_ai_json_response(
                task="generator",
                model=server.FACTS_AI_GENERATOR_MODEL,
                prompt="Prompt",
                schema={"type": "object"},
            )

        self.assertEqual(payload, fallback_payload)
        self.assertEqual(compatible_request.call_count, 2)

    def test_public_history_fact_hides_internal_critique(self) -> None:
        import server

        public_fact = server.public_history_fact(
            {
                "title": "Paisley Abbey",
                "text": "Paisley Abbey is a medieval landmark in the town.",
                "theme": "landmark",
                "sourceName": "Wikipedia + Wikidata",
                "sourceUrl": "https://example.com/abbey",
                "confidence": "high",
                "critique": {
                    "summary": "Internal only",
                    "relevance": 10,
                    "interestingness": 9,
                    "placeSpecificity": 10,
                },
            }
        )

        self.assertNotIn("critique", public_fact)
        self.assertEqual(public_fact["sourceName"], "Wikipedia + Wikidata")

    def test_history_fact_review_failures_are_cached_for_future_attempts(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name) / "runtime-db"
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()
            rotation_key = server.history_fact_rotation_key("Paisley, Renfrewshire", "en")

            server.store_history_fact_review_failure(
                rotation_key,
                selection={"facts": [{"candidateIndex": 2, "title": "Generic fact", "text": "Paisley is a town in Scotland."}]},
                critique={"overallPassed": False, "notes": "Too generic."},
                failure_reason="Gemini critique rejected the selected facts.",
            )

            failures = server.recent_history_fact_review_failures(rotation_key)

            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]["failureReason"], "Gemini critique rejected the selected facts.")
            self.assertEqual(failures[0]["selection"]["facts"][0]["candidateIndex"], 2)
            self.assertEqual(failures[0]["critique"]["notes"], "Too generic.")
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_history_fact_rotation_expires_after_24_hours(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name) / "runtime-db"
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            rotation_key = server.history_fact_rotation_key("Paisley, Renfrewshire", "en")
            facts = [
                {
                    "title": "Paisley Abbey",
                    "text": "Paisley Abbey is a medieval landmark in the town.",
                    "theme": "landmark",
                    "sourceName": "Wikipedia",
                    "sourceUrl": "https://example.com/abbey",
                    "confidence": "medium",
                }
            ]
            created_at = (datetime.now(timezone.utc) - timedelta(hours=23)).replace(microsecond=0).isoformat()
            server.store_rotated_history_facts(rotation_key, facts, created_at=created_at)

            active = server.current_rotated_history_facts(
                rotation_key,
                now=datetime.now(timezone.utc),
            )
            expired = server.current_rotated_history_facts(
                rotation_key,
                now=datetime.now(timezone.utc) + timedelta(hours=2),
            )

            self.assertEqual(active, facts)
            self.assertIsNone(expired)
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_history_cache_get_discards_cached_payload_without_location(self) -> None:
        import server

        server.HISTORY_CACHE.clear()
        self.addCleanup(server.HISTORY_CACHE.clear)
        server.HISTORY_CACHE["history:test"] = (
            server.time.time() + 60,
            {
                "request": {"location": "Paisley", "date": "2026-06-04", "lang": "en"},
                "location": None,
                "globalEvents": [],
                "partial": True,
                "warnings": [
                    {
                        "source": "wikipedia",
                        "code": "upstream_unavailable",
                        "detail": "Location facts are currently unavailable.",
                    }
                ],
                "meta": {"cached": False, "generatedAt": "2026-06-04T10:00:00+00:00"},
            },
        )

        cached = server.history_cache_get("history:test")

        self.assertIsNone(cached)
        self.assertNotIn("history:test", server.HISTORY_CACHE)

    def test_history_payload_does_not_cache_partial_result_without_location(self) -> None:
        import server

        server.HISTORY_CACHE.clear()
        self.addCleanup(server.HISTORY_CACHE.clear)
        fetch_summary_calls = 0
        rotation_created_at = datetime(2026, 6, 4, 11, 30, 0, tzinfo=timezone.utc)

        def fake_fetch_summary(_location: str, _lang: str) -> dict[str, object]:
            nonlocal fetch_summary_calls
            fetch_summary_calls += 1
            if fetch_summary_calls == 1:
                raise RuntimeError("Temporary upstream failure")
            return {
                "title": "Paisley",
                "description": "Town in Scotland",
                "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Paisley"}},
                "thumbnail": {"source": "https://example.com/paisley.jpg"},
            }

        rotated_facts = [
            {
                "title": "Paisley Abbey",
                "text": "Paisley Abbey is one of the town's best-known landmarks.",
                "theme": "history",
                "sourceName": "Paisley Abbey",
                "sourceUrl": "https://paisleyabbey.org.uk/history",
                "confidence": "high",
            }
        ]
        events = [{"year": "1163", "description": "A notable event."}]

        with (
            patch("server.fetch_wikipedia_summary", side_effect=fake_fetch_summary),
            patch("server.fetch_history_events", return_value=events),
            patch("server.fetch_wikipedia_plain_extract", return_value="Paisley is a town in Scotland."),
            patch("server.fetch_wikipedia_images", return_value=[]),
            patch(
                "server.current_rotated_history_facts_record",
                return_value=(rotated_facts, rotation_created_at),
            ),
            patch("server.schedule_history_fact_prewarm", return_value=False),
            patch("server.wikidata_profile", return_value={}),
        ):
            first_payload, first_status = server.history_payload("Paisley", "2026-06-04", "en", 2, 5)
            self.assertEqual(first_status, HTTPStatus.OK)
            self.assertIsNone(first_payload["location"])
            self.assertEqual(first_payload["globalEvents"], events)
            self.assertNotIn("en:paisley:2026-06-04:2:5", server.HISTORY_CACHE)

            second_payload, second_status = server.history_payload("Paisley", "2026-06-04", "en", 2, 5)

        self.assertEqual(second_status, HTTPStatus.OK)
        self.assertEqual(fetch_summary_calls, 2)
        self.assertIsInstance(second_payload["location"], dict)
        self.assertEqual(second_payload["location"]["title"], "Paisley")
        self.assertEqual(second_payload["location"]["facts"][0]["title"], "Paisley Abbey")
        self.assertFalse(second_payload["meta"]["cached"])
        self.assertEqual(second_payload["meta"]["rotationCreatedAt"], "2026-06-04T11:30:00+00:00")
        self.assertEqual(second_payload["meta"]["rotationExpiresAt"], "2026-06-05T11:30:00+00:00")
        self.assertIn("en:paisley:2026-06-04:2:5", server.HISTORY_CACHE)

    def test_history_payload_cache_expires_when_fact_rotation_expires(self) -> None:
        import server

        server.HISTORY_CACHE.clear()
        self.addCleanup(server.HISTORY_CACHE.clear)

        rotation_created_at = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=23)
        rotated_facts = [
            {
                "title": "Paisley Abbey",
                "text": "Paisley Abbey is one of the town's best-known landmarks.",
                "theme": "history",
                "sourceName": "Paisley Abbey",
                "sourceUrl": "https://paisleyabbey.org.uk/history",
                "confidence": "high",
            }
        ]

        with (
            patch(
                "server.fetch_wikipedia_summary",
                return_value={
                    "title": "Paisley",
                    "description": "Town in Scotland",
                    "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Paisley"}},
                    "thumbnail": {"source": "https://example.com/paisley.jpg"},
                },
            ),
            patch("server.fetch_history_events", return_value=[]),
            patch("server.fetch_wikipedia_plain_extract", return_value="Paisley is a town in Scotland."),
            patch("server.fetch_wikipedia_images", return_value=[]),
            patch(
                "server.current_rotated_history_facts_record",
                return_value=(rotated_facts, rotation_created_at),
            ),
            patch("server.schedule_history_fact_prewarm", return_value=False),
            patch("server.wikidata_profile", return_value={}),
        ):
            _payload, status = server.history_payload("Paisley", "2026-06-04", "en", 2, 5)

        self.assertEqual(status, HTTPStatus.OK)
        expires_at, cached_payload = server.HISTORY_CACHE["en:paisley:2026-06-04:2:5"]
        expected_expiry = rotation_created_at.timestamp() + server.FACT_ROTATION_TTL_SEC
        self.assertAlmostEqual(expires_at, expected_expiry, delta=1.0)
        self.assertEqual(
            cached_payload["meta"]["rotationExpiresAt"],
            (rotation_created_at + timedelta(seconds=server.FACT_ROTATION_TTL_SEC)).isoformat(),
        )

    def test_schedule_history_fact_prewarm_avoids_duplicate_active_job(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name) / "runtime-db"
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            now = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)
            source_rotation_created_at = now - timedelta(
                seconds=server.FACT_ROTATION_TTL_SEC - 1800
            )

            first = server.schedule_history_fact_prewarm(
                rotation_key="v4:en:paisley",
                location_query="Paisley",
                place_title="Paisley, Renfrewshire",
                lang="en",
                limit_facts=2,
                source_rotation_created_at=source_rotation_created_at,
                now=now,
            )
            second = server.schedule_history_fact_prewarm(
                rotation_key="v4:en:paisley",
                location_query="Paisley",
                place_title="Paisley, Renfrewshire",
                lang="en",
                limit_facts=2,
                source_rotation_created_at=source_rotation_created_at,
                now=now,
            )

            with closing(server.connect_db()) as conn:
                rows = conn.execute(
                    """
                    SELECT rotation_key, status, target_not_before_at
                    FROM history_fact_prewarm_jobs
                    ORDER BY id ASC
                    """
                ).fetchall()

            self.assertTrue(first)
            self.assertFalse(second)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["rotation_key"], "v4:en:paisley")
            self.assertEqual(rows[0]["status"], "pending")
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_promote_ready_history_fact_prewarm_consumes_job_and_stores_rotation(self) -> None:
        import server

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name) / "runtime-db"
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()

            facts = [
                {
                    "title": "Royal Birthplace",
                    "text": "Robert II was born in Paisley in 1316.",
                    "theme": "people",
                    "sourceName": "paisley.is",
                    "sourceUrl": "https://paisley.is/visit/paisley/",
                    "confidence": "medium",
                },
                {
                    "title": "Paisley Pattern",
                    "text": "Paisley's textile industry made the pattern famous worldwide.",
                    "theme": "industry",
                    "sourceName": "bbc.com",
                    "sourceUrl": "https://www.bbc.com/culture/article/paisley-pattern",
                    "confidence": "medium",
                },
            ]

            with closing(server.connect_db()) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO history_fact_prewarm_jobs (
                            rotation_key,
                            location_query,
                            place_title,
                            lang,
                            limit_facts,
                            source_rotation_created_at,
                            target_not_before_at,
                            status,
                            facts_json,
                            attempts,
                            created_at,
                            completed_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'ready', ?, 1, ?, ?)
                        """,
                        (
                            "v4:en:paisley",
                            "Paisley",
                            "Paisley, Renfrewshire",
                            "en",
                            2,
                            "2026-06-05T11:00:00+00:00",
                            "2026-06-06T11:00:00+00:00",
                            json.dumps(facts, ensure_ascii=True),
                            "2026-06-06T10:00:00+00:00",
                            "2026-06-06T10:05:00+00:00",
                        ),
                    )

            promoted = server.promote_ready_history_fact_prewarm(
                "v4:en:paisley",
                now=datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc),
            )

            self.assertIsNotNone(promoted)
            promoted_facts, promoted_created_at = promoted or ([], datetime.now(timezone.utc))
            self.assertEqual(len(promoted_facts), 2)
            self.assertEqual(promoted_facts[0]["title"], "Royal Birthplace")
            self.assertIsNotNone(promoted_created_at)

            with closing(server.connect_db()) as conn:
                rotation = conn.execute(
                    """
                    SELECT facts_json
                    FROM history_fact_rotations
                    WHERE rotation_key = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    ("v4:en:paisley",),
                ).fetchone()
                job = conn.execute(
                    "SELECT status FROM history_fact_prewarm_jobs WHERE rotation_key = ?",
                    ("v4:en:paisley",),
                ).fetchone()

            self.assertIsNotNone(rotation)
            self.assertEqual(json.loads(str(rotation["facts_json"]))[0]["title"], "Royal Birthplace")
            self.assertEqual(job["status"], "consumed")
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_history_payload_promotes_ready_prewarm_before_cold_regeneration(self) -> None:
        import server

        server.HISTORY_CACHE.clear()
        self.addCleanup(server.HISTORY_CACHE.clear)
        ready_facts = [
            {
                "title": "Royal Birthplace",
                "text": "Robert II was born in Paisley in 1316.",
                "theme": "people",
                "sourceName": "paisley.is",
                "sourceUrl": "https://paisley.is/visit/paisley/",
                "confidence": "medium",
            },
            {
                "title": "Paisley Pattern",
                "text": "Paisley's textile industry made the pattern famous worldwide.",
                "theme": "industry",
                "sourceName": "bbc.com",
                "sourceUrl": "https://www.bbc.com/culture/article/paisley-pattern",
                "confidence": "medium",
            },
        ]
        promoted_created_at = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)
        location_context = {
            "title": "Paisley",
            "description": "Town in Scotland",
            "articleUrl": "https://en.wikipedia.org/wiki/Paisley",
            "thumbnailUrl": "https://example.com/paisley.jpg",
            "wiki": {},
            "plainExtract": "Paisley is a town in Scotland.",
            "wikidataEntity": None,
            "locationImages": [],
        }

        with (
            patch("server.load_history_location_context", return_value=location_context),
            patch("server.fetch_history_events", return_value=[]),
            patch("server.current_rotated_history_facts_record", return_value=None),
            patch(
                "server.promote_ready_history_fact_prewarm",
                return_value=(ready_facts, promoted_created_at),
            ) as promote_ready,
            patch("server.build_history_rotation_facts_from_context") as cold_build,
            patch("server.wikidata_profile", return_value={}),
        ):
            payload, status = server.history_payload("Paisley", "2026-06-06", "en", 2, 5)

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(payload["location"]["facts"][0]["title"], "Royal Birthplace")
        self.assertEqual(payload["meta"]["rotationCreatedAt"], "2026-06-06T12:00:00+00:00")
        promote_ready.assert_called_once()
        cold_build.assert_not_called()

    def test_history_payload_enqueues_prewarm_for_near_expiry_rotation(self) -> None:
        import server

        server.HISTORY_CACHE.clear()
        self.addCleanup(server.HISTORY_CACHE.clear)
        rotation_created_at = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(
            seconds=server.FACT_ROTATION_TTL_SEC - 1800
        )
        rotated_facts = [
            {
                "title": "Paisley Abbey",
                "text": "Paisley Abbey is one of the town's best-known landmarks.",
                "theme": "history",
                "sourceName": "Paisley Abbey",
                "sourceUrl": "https://paisleyabbey.org.uk/history",
                "confidence": "high",
            }
        ]
        location_context = {
            "title": "Paisley",
            "description": "Town in Scotland",
            "articleUrl": "https://en.wikipedia.org/wiki/Paisley",
            "thumbnailUrl": "https://example.com/paisley.jpg",
            "wiki": {},
            "plainExtract": "Paisley is a town in Scotland.",
            "wikidataEntity": None,
            "locationImages": [],
        }

        with (
            patch("server.load_history_location_context", return_value=location_context),
            patch("server.fetch_history_events", return_value=[]),
            patch(
                "server.current_rotated_history_facts_record",
                return_value=(rotated_facts, rotation_created_at),
            ),
            patch("server.schedule_history_fact_prewarm", return_value=True) as schedule_prewarm,
            patch("server.wikidata_profile", return_value={}),
        ):
            payload, status = server.history_payload("Paisley", "2026-06-06", "en", 2, 5)

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(payload["location"]["facts"][0]["title"], "Paisley Abbey")
        schedule_prewarm.assert_called_once()
        self.assertEqual(
            schedule_prewarm.call_args.kwargs["rotation_key"],
            "v4:en:paisleyrenfrewshire",
        )
        self.assertEqual(schedule_prewarm.call_args.kwargs["location_query"], "Paisley")

    def test_history_payload_cache_hit_still_enqueues_prewarm(self) -> None:
        import server

        server.HISTORY_CACHE.clear()
        self.addCleanup(server.HISTORY_CACHE.clear)
        cache_key = "en:paisley:2026-06-06:2:5"
        cached_payload = {
            "request": {"location": "Paisley", "date": "2026-06-06", "lang": "en"},
            "location": {
                "title": "Paisley",
                "description": "Town in Scotland",
                "facts": [
                    {
                        "title": "Paisley Abbey",
                        "text": "Paisley Abbey is one of the town's best-known landmarks.",
                        "theme": "history",
                        "sourceName": "Paisley Abbey",
                        "sourceUrl": "https://paisleyabbey.org.uk/history",
                        "confidence": "high",
                    }
                ],
                "articleUrl": "https://en.wikipedia.org/wiki/Paisley",
                "thumbnailUrl": "https://example.com/paisley.jpg",
                "images": [],
            },
            "globalEvents": [],
            "partial": False,
            "warnings": [],
            "meta": {
                "cached": False,
                "eventsLanguage": "en",
                "generatedAt": "2026-06-06T10:30:00+00:00",
                "rotationCreatedAt": (
                    datetime.now(timezone.utc).replace(microsecond=0)
                    - timedelta(seconds=server.FACT_ROTATION_TTL_SEC - 1800)
                ).isoformat(),
                "rotationExpiresAt": None,
            },
        }
        server.HISTORY_CACHE[cache_key] = (server.time.time() + 60, cached_payload)

        with patch("server.schedule_history_fact_prewarm", return_value=True) as schedule_prewarm:
            payload, status = server.history_payload("Paisley", "2026-06-06", "en", 2, 5)

        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(payload["meta"]["cached"])
        schedule_prewarm.assert_called_once()

    def test_wikipedia_images_keep_location_photos_and_skip_badges(self) -> None:
        import server

        summary = {
            "title": "Paisley, Renfrewshire",
            "thumbnail": {"source": "https://upload.wikimedia.org/paisley-lead.jpg"},
        }
        article_url = "https://en.wikipedia.org/wiki/Paisley,_Renfrewshire"
        media_payload = {
            "query": {
                "pages": {
                    "1": {
                        "title": "File:Paisley town centre.jpg",
                        "imageinfo": [{
                            "thumburl": "https://upload.wikimedia.org/paisley-town-centre.jpg",
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Paisley_town_centre.jpg",
                        }],
                    },
                    "2": {
                        "title": "File:Paisley coat of arms.svg",
                        "imageinfo": [{
                            "thumburl": "https://upload.wikimedia.org/paisley-arms.svg",
                        }],
                    },
                    "3": {
                        "title": "File:Paisley Abbey.png",
                        "imageinfo": [{
                            "url": "https://upload.wikimedia.org/paisley-abbey.png",
                        }],
                    },
                }
            }
        }

        with patch("server.fetch_json_url", return_value=media_payload) as fetch:
            images = server.fetch_wikipedia_images(summary, "en", article_url, limit=4)

        self.assertEqual(
            [image["url"] for image in images],
            [
                "https://upload.wikimedia.org/paisley-lead.jpg",
                "https://upload.wikimedia.org/paisley-town-centre.jpg",
                "https://upload.wikimedia.org/paisley-abbey.png",
            ],
        )
        self.assertEqual(images[0]["sourceName"], "Wikipedia")
        self.assertEqual(images[1]["sourceName"], "Wikimedia Commons")
        self.assertIn("generator=images", fetch.call_args[0][0])

    def test_fact_images_only_attach_when_media_title_matches_fact_text(self) -> None:
        import server

        facts = [
            {
                "title": "Landmark",
                "text": "Paisley Abbey is a medieval landmark in the town.",
                "theme": "landmark",
            },
            {
                "title": "Industry",
                "text": "Paisley became a global centre of the weaving industry.",
                "theme": "industry",
            },
        ]
        images = [
            {
                "url": "https://upload.wikimedia.org/paisley-abbey.jpg",
                "title": "Paisley Abbey from the west.jpg",
                "sourceName": "Wikimedia Commons",
                "sourceUrl": None,
            },
            {
                "url": "https://upload.wikimedia.org/townscape.jpg",
                "title": "Paisley town centre.jpg",
                "sourceName": "Wikimedia Commons",
                "sourceUrl": None,
            },
        ]

        matched = server.attach_fact_images(facts, images, "Paisley, Renfrewshire")

        self.assertEqual(matched[0]["image"]["title"], "Paisley Abbey from the west.jpg")
        self.assertNotIn("image", matched[1])

    def test_missing_fact_image_can_be_retrieved_from_commons_search(self) -> None:
        import server

        fact = {
            "title": "Landmark",
            "text": "Paisley Abbey is a medieval landmark in the town.",
            "theme": "landmark",
        }
        search_payload = {
            "query": {
                "pages": {
                    "1": {
                        "title": "File:Paisley Abbey cloisters.jpg",
                        "imageinfo": [{
                            "thumburl": "https://upload.wikimedia.org/paisley-abbey-cloisters.jpg",
                        }],
                    },
                }
            }
        }

        with patch("server.fetch_json_url", return_value=search_payload) as fetch:
            image = server.fetch_commons_fact_image(fact, "Paisley, Renfrewshire")

        self.assertEqual(image["title"], "Paisley Abbey cloisters.jpg")
        self.assertIn("commons.wikimedia.org", fetch.call_args[0][0])
        self.assertIn("generator=search", fetch.call_args[0][0])

    def test_fact_image_queries_include_shorter_fact_searches(self) -> None:
        import server

        queries = server.fact_image_queries(
            {
                "title": "Industry",
                "text": (
                    "Paisley became a global centre of the weaving industry, "
                    "giving its name to the Paisley shawl and Paisley pattern."
                ),
            },
            "Paisley, Renfrewshire",
        )

        self.assertIn("Paisley weaving industry shawl pattern", queries)
        self.assertIn("Paisley shawl pattern", queries)

    def test_fact_image_match_rejects_wrong_roman_numeral_person(self) -> None:
        import server

        score = server.fact_image_match_score(
            {
                "title": "People",
                "text": "Robert II is believed to have been born in Paisley Abbey.",
            },
            {
                "url": "https://upload.wikimedia.org/robert-iii.jpg",
                "title": "King Robert III memorial, Paisley Abbey.jpg",
                "sourceName": "Wikimedia Commons",
                "sourceUrl": None,
            },
            server.fact_image_terms("Paisley, Renfrewshire"),
        )

        self.assertEqual(score, 0)

    def test_wordle_points_curve(self) -> None:
        import server

        self.assertEqual([server.wordle_score("won", attempt) for attempt in range(1, 7)], [10, 5, 4, 3, 2, 1])
        self.assertEqual(server.wordle_score("won", 3, difficulty=4), 10)
        self.assertEqual(server.wordle_score("won", 1, difficulty=20), 48)
        self.assertEqual(server.wordle_score("lost", 6), 0)
        self.assertEqual(server.wordle_score("lost", 3, difficulty=20), 0)

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

            def read(self) -> bytes:
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

    def test_quiz_scoring_adds_perfect_round_bonus(self) -> None:
        import server

        questions = [
            {"difficulty": "easy", "correct_answer": "A"},
            {"difficulty": "medium", "correct_answer": "B"},
            {"difficulty": "hard", "correct_answer": "C"},
        ]

        self.assertEqual(
            server.score_quiz_answers(questions, ["A", "B", "C"]),
            {"score": 12, "maxScore": 12, "correctCount": 3, "bonusPoints": 3},
        )
        self.assertEqual(
            server.score_quiz_answers(questions, ["A", "wrong", "C"]),
            {"score": 6, "maxScore": 12, "correctCount": 2, "bonusPoints": 0},
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
                    first, first_status = server.save_daily_quiz_result(
                        conn,
                        user_id,
                        "2026-06-01",
                        "football",
                        ["A", "wrong", "C"],
                    )
                    repeated, repeated_status = server.save_daily_quiz_result(
                        conn,
                        user_id,
                        "2026-06-01",
                        "football",
                        ["wrong", "wrong", "wrong"],
                    )
                    leaderboard = server.leaderboard_payload(conn)

            self.assertEqual(first_status, HTTPStatus.CREATED)
            self.assertEqual(repeated_status, HTTPStatus.OK)
            self.assertEqual(first["result"]["score"], 6)
            self.assertEqual(first["result"]["maxScore"], 12)
            self.assertEqual(first["result"]["bonusPoints"], 0)
            self.assertEqual(repeated["result"]["score"], 6)
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

    def test_leaderboard_excludes_admin_accounts(self) -> None:
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

            self.assertEqual([player["username"] for player in payload["players"]], ["dad"])
            self.assertEqual(payload["players"][0]["totalPoints"], 6)
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

    def test_history_events_prefer_recent_sport_and_birth_highlights(self) -> None:
        import server

        source_payload = {
            "data": {
                "Events": [
                    {"year": "45 BC", "text": "A very old event happened.", "links": []},
                    {"year": "2021", "text": "A landmark science mission launched.", "links": []},
                    {"year": "1967", "text": "A football club won a European cup.", "links": []},
                    {"year": "1998", "text": "A major agreement was signed.", "links": []},
                ],
                "Births": [
                    {"year": "1987", "text": "A famous singer and actor was born.", "links": []},
                    {"year": "1880", "text": "A local clerk was born.", "links": []},
                ],
            }
        }

        with patch("server.fetch_json_url", return_value=source_payload):
            events = server.fetch_history_events(5, 21, 5)

        categories = {event.get("category") for event in events}
        event_text = " ".join(event["text"] for event in events)

        self.assertIn("history", categories)
        self.assertIn("sport", categories)
        self.assertIn("born", categories)
        self.assertIn("football club won", event_text)
        self.assertIn("famous singer and actor", event_text)
        self.assertNotEqual(events[0]["year"], "45 BC")

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
            required_place_type=None,
        )
        self.assertEqual(generate.call_args.kwargs["eligible_names"], {"fresh stadium"})
        self.assertIsNone(generate.call_args.kwargs["required_place_type"])

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


if __name__ == "__main__":
    unittest.main()

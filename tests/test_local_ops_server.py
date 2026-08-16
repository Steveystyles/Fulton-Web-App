from __future__ import annotations

import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

import local_ops_server


class LocalOpsServerIsolationTests(unittest.TestCase):
    @staticmethod
    def authorized_handler(
        *,
        payload: dict[str, object] | None = None,
    ) -> tuple[object, list[tuple[int, object]]]:
        sent: list[tuple[int, object]] = []

        class Handler:
            def ops_request_authorized(self, _method: str) -> bool:
                return True

            def read_json(self) -> dict[str, object]:
                return payload or {}

            def send_json(self, status: int, body: object) -> None:
                sent.append((status, body))

            def send_error_json(self, status: int, message: str) -> None:
                raise AssertionError(f"unexpected API error {status}: {message}")

        return Handler(), sent

    def test_access_token_must_be_strong_and_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            token_path = Path(temp_dir) / "token"
            token_path.write_text("too-short", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                local_ops_server.load_access_token(token_path)
            token_path.write_text("a" * 43, encoding="utf-8")
            self.assertEqual(local_ops_server.load_access_token(token_path), "a" * 43)

    def test_authorization_requires_loopback_host_and_token(self) -> None:
        class Handler:
            ops_access_token = "t" * 43
            ops_port = 8765
            headers = {
                "Host": "127.0.0.1:8765",
                local_ops_server.TOKEN_HEADER: "t" * 43,
            }

            def is_loopback_request(self) -> bool:
                return True

            request_host_allowed = local_ops_server.LocalOpsHandler.request_host_allowed
            request_origin_allowed = local_ops_server.LocalOpsHandler.request_origin_allowed

        handler = Handler()
        self.assertTrue(handler.request_host_allowed())
        self.assertTrue(
            local_ops_server.LocalOpsHandler.ops_request_authorized(handler, "GET")  # type: ignore[arg-type]
        )
        handler.headers["Host"] = "attacker.example"
        self.assertFalse(
            local_ops_server.LocalOpsHandler.ops_request_authorized(handler, "GET")  # type: ignore[arg-type]
        )

    def test_mutation_requires_exact_loopback_origin(self) -> None:
        class Handler:
            ops_access_token = "t" * 43
            ops_port = 8765
            headers = {
                "Host": "localhost:8765",
                local_ops_server.TOKEN_HEADER: "t" * 43,
            }

            def is_loopback_request(self) -> bool:
                return True

            request_host_allowed = local_ops_server.LocalOpsHandler.request_host_allowed
            request_origin_allowed = local_ops_server.LocalOpsHandler.request_origin_allowed

        handler = Handler()
        self.assertFalse(
            local_ops_server.LocalOpsHandler.ops_request_authorized(handler, "POST")  # type: ignore[arg-type]
        )
        handler.headers["Origin"] = "http://localhost:8765"
        self.assertTrue(
            local_ops_server.LocalOpsHandler.ops_request_authorized(handler, "POST")  # type: ignore[arg-type]
        )
        handler.headers["Origin"] = "http://attacker.example"
        self.assertFalse(
            local_ops_server.LocalOpsHandler.ops_request_authorized(handler, "POST")  # type: ignore[arg-type]
        )

    def test_invalid_config_is_returned_as_bad_request(self) -> None:
        sent: list[tuple[int, str]] = []

        class Handler:
            def ops_request_authorized(self, _method: str) -> bool:
                return True

            def read_json(self) -> dict[str, str]:
                return {"sshTarget": "-oProxyCommand=calc"}

            def send_error_json(self, status: int, message: str) -> None:
                sent.append((status, message))

            def send_json(self, *_args: object, **_kwargs: object) -> None:
                raise AssertionError("invalid configuration must not succeed")

        with patch(
            "local_ops_server.local_ops_settings.save_monitor_settings",
            side_effect=ValueError("sshTarget is invalid"),
        ):
            local_ops_server.LocalOpsHandler.route_api(  # type: ignore[arg-type]
                Handler(),
                "POST",
                "/api/local/ops-config",
            )

        self.assertEqual(sent, [(HTTPStatus.BAD_REQUEST, "sshTarget is invalid")])

    def test_monitor_and_config_get_dispatch_successfully(self) -> None:
        handler, sent = self.authorized_handler()
        snapshot = {"status": "ok"}
        config = {"sshTarget": "ste@example.invalid", "tokenConfigured": True}
        with (
            patch(
                "local_ops_server.ops_monitor.collect_dashboard_snapshot",
                return_value=snapshot,
            ) as collect,
            patch(
                "local_ops_server.local_ops_settings.monitor_settings_response",
                return_value=config,
            ),
        ):
            local_ops_server.LocalOpsHandler.route_api(  # type: ignore[arg-type]
                handler,
                "GET",
                "/api/local/ops-monitor",
                "force=true",
            )
            local_ops_server.LocalOpsHandler.route_api(  # type: ignore[arg-type]
                handler,
                "GET",
                "/api/local/ops-config",
            )

        collect.assert_called_once_with(force=True)
        self.assertEqual(
            sent,
            [(HTTPStatus.OK, snapshot), (HTTPStatus.OK, config)],
        )

    def test_config_save_dispatches_and_returns_redacted_response(self) -> None:
        handler, sent = self.authorized_handler(payload={"sshTarget": "ste@host"})
        saved = {"sshTarget": "ste@host", "tokenConfigured": True}
        with (
            patch(
                "local_ops_server.local_ops_settings.save_monitor_settings",
                return_value=saved,
            ) as save,
            patch(
                "local_ops_server.local_ops_settings.SETTINGS_PATH",
                Path("settings.json"),
            ),
        ):
            local_ops_server.LocalOpsHandler.route_api(  # type: ignore[arg-type]
                handler,
                "POST",
                "/api/local/ops-config",
            )

        save.assert_called_once_with({"sshTarget": "ste@host"})
        self.assertEqual(
            sent,
            [
                (
                    HTTPStatus.OK,
                    {"config": saved, "settingsPath": "settings.json"},
                )
            ],
        )

    def test_sync_and_async_actions_dispatch_to_separate_runners(self) -> None:
        sync_handler, sync_sent = self.authorized_handler(
            payload={"action": "refresh", "params": {"date": "2026-08-15"}}
        )
        async_handler, async_sent = self.authorized_handler(
            payload={"action": "generate", "params": {"date": "2026-08-16"}}
        )
        with (
            patch(
                "local_ops_server.ops_monitor.is_async_local_action",
                side_effect=[False, True],
            ),
            patch(
                "local_ops_server.ops_monitor.run_local_action",
                return_value={"status": "complete"},
            ) as run,
            patch(
                "local_ops_server.ops_monitor.start_local_action_job",
                return_value={"jobId": "job-1", "status": "queued"},
            ) as start,
        ):
            local_ops_server.LocalOpsHandler.route_api(  # type: ignore[arg-type]
                sync_handler,
                "POST",
                "/api/local/ops-action",
            )
            local_ops_server.LocalOpsHandler.route_api(  # type: ignore[arg-type]
                async_handler,
                "POST",
                "/api/local/ops-action",
            )

        run.assert_called_once_with("refresh", params={"date": "2026-08-15"})
        start.assert_called_once_with("generate", params={"date": "2026-08-16"})
        self.assertEqual(sync_sent, [(HTTPStatus.OK, {"status": "complete"})])
        self.assertEqual(
            async_sent,
            [(HTTPStatus.ACCEPTED, {"jobId": "job-1", "status": "queued"})],
        )

    def test_action_status_dispatches_job_id(self) -> None:
        handler, sent = self.authorized_handler()
        result = {"jobId": "job-1", "status": "complete"}
        with patch(
            "local_ops_server.ops_monitor.get_local_action_job",
            return_value=result,
        ) as get_job:
            local_ops_server.LocalOpsHandler.route_api(  # type: ignore[arg-type]
                handler,
                "GET",
                "/api/local/ops-action-status",
                "jobId=job-1",
            )

        get_job.assert_called_once_with("job-1")
        self.assertEqual(sent, [(HTTPStatus.OK, result)])

    def test_non_local_api_is_not_forwarded_to_player_server(self) -> None:
        sent: list[tuple[int, str]] = []

        class Handler:
            def send_error_json(self, status: int, message: str) -> None:
                sent.append((status, message))

        local_ops_server.LocalOpsHandler.route_api(  # type: ignore[arg-type]
            Handler(),
            "GET",
            "/api/auth/me",
        )
        self.assertEqual(sent, [(HTTPStatus.NOT_FOUND, "API route not found.")])


if __name__ == "__main__":
    unittest.main()

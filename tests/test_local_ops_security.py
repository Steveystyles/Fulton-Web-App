from __future__ import annotations

import json
import os
import queue
import stat
import tempfile
import threading
import unittest
from concurrent.futures import Future
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

import local_ops_settings
import ops_monitor


class HoldingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[object, tuple[object, ...]]] = []

    def submit(self, function, /, *args, **_kwargs) -> Future:
        self.calls.append((function, args))
        return Future()


def monitor_config(**overrides) -> ops_monitor.MonitorConfig:
    values = {
        "enabled": True,
        "cache_ttl_sec": 15,
        "ssh_target": "ste@192.168.0.15",
        "ssh_port": 22,
        "ssh_key_path": str(Path.home() / ".ssh" / "codex_fultons_ed25519"),
        "ssh_connect_timeout_sec": 6,
        "public_health_url": local_ops_settings.CANONICAL_PUBLIC_HEALTH_URL,
        "internal_base_url": "https://fultons-quiz.co.uk",
        "internal_quiz_token": "test-secret-token",
        "compose_file": "/home/ste/fulton-web-app-deploy/compose.yaml",
        "env_file": "/srv/storage/appdata/fultons-quiz/app.env",
        "data_dir": "/srv/storage/appdata/fultons-quiz",
        "db_path": "/srv/storage/appdata/fultons-quiz/fultons.db",
        "app_port": 3000,
    }
    values.update(overrides)
    return ops_monitor.MonitorConfig(**values)


class LocalOpsSettingsSecurityTests(unittest.TestCase):
    def test_map_alerts_only_require_wednesday_and_saturday_rounds(self) -> None:
        remote = {
            "quiz": {"today": {"status": "published"}, "tomorrow": {"status": "published"}},
            "map": {
                "today": {"date": "2026-10-02", "status": "missing"},
                "tomorrow": {"date": "2026-10-03", "status": "missing"},
            },
        }
        alerts = ops_monitor.build_alerts(remote, {"ok": True})
        self.assertNotIn("Today map is missing.", alerts)
        self.assertIn("Tomorrow map is missing.", alerts)
        remote["map"]["tomorrow"]["status"] = "published"
        self.assertTrue(ops_monitor.build_snapshot({"ok": True}, remote)["ok"])
        remote["map"]["today"] = {"date": "2026-10-07", "status": "missing"}
        self.assertIn("Today map is missing.", ops_monitor.build_alerts(remote, {"ok": True}))

    def test_ssh_probe_map_checks_use_the_same_schedule(self) -> None:
        namespace = {"__name__": "remote_probe_test"}
        exec(ops_monitor.REMOTE_PROBE_SCRIPT, namespace)
        readiness = namespace["map_readiness_test"]
        self.assertEqual(readiness("today_map", "Today map", "2026-10-02", {"status": "missing"})["status"], "pass")
        self.assertEqual(readiness("tomorrow_map", "Tomorrow map", "2026-10-03", {"status": "missing"})["status"], "fail")
        self.assertEqual(readiness("today_map", "Today map", "2026-10-07", {"status": "published"})["status"], "pass")

    def test_ssh_target_rejects_option_whitespace_control_and_unlisted_hosts(self) -> None:
        invalid_targets = (
            "-oProxyCommand=calc",
            "ste@192.168.0.15 -oProxyCommand=calc",
            "ste@192.168.0.15\n-oProxyCommand=calc",
            "ste@example.com",
            "root@192.168.0.15",
            "ste@127.0.0.1",
        )
        for target in invalid_targets:
            with self.subTest(target=repr(target)):
                with self.assertRaises(ValueError):
                    local_ops_settings.validate_ssh_target(target)

        self.assertEqual(
            local_ops_settings.validate_ssh_target("ste@192.168.0.15"),
            "ste@192.168.0.15",
        )

    def test_ssh_key_path_rejects_unc_device_traversal_and_symlink_components(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            ssh_root = base / ".ssh"
            ssh_root.mkdir()
            key_path = ssh_root / "ops_key"
            key_path.write_text("not-a-real-key", encoding="utf-8")

            for unsafe in (r"\\server\share\key", r"\\?\C:\Users\user\.ssh\key"):
                with self.subTest(path=unsafe):
                    with self.assertRaises(ValueError):
                        local_ops_settings.validate_ssh_key_path(
                            unsafe,
                            expected_root=ssh_root,
                        )

            with self.assertRaises(ValueError):
                local_ops_settings.validate_ssh_key_path(
                    str(ssh_root / ".." / "outside-key"),
                    expected_root=ssh_root,
                )

            with patch("local_ops_settings._path_has_symlink_component", return_value=True):
                with self.assertRaises(ValueError):
                    local_ops_settings.validate_ssh_key_path(
                        str(key_path),
                        expected_root=ssh_root,
                    )

    def test_url_allowlists_reject_file_and_ssrf_destinations(self) -> None:
        invalid_public = (
            "file:///C:/Windows/win.ini",
            "http://127.0.0.1:8765/api/health",
            "https://fultons-quiz.co.uk:444/api/health",
            "https://user:pass@fultons-quiz.co.uk/api/health",
        )
        for url in invalid_public:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    local_ops_settings.validate_public_health_url(url)

        invalid_internal = (
            "file:///etc/passwd",
            "http://169.254.169.254/latest/meta-data",
            "http://127.0.0.1:22",
            "https://evil.example",
            "https://user:pass@fultons-quiz.co.uk",
        )
        for url in invalid_internal:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    local_ops_settings.validate_internal_base_url(url)

        self.assertEqual(
            local_ops_settings.validate_internal_base_url("http://127.0.0.1:8765"),
            "http://127.0.0.1:8765",
        )
        self.assertEqual(
            local_ops_settings.validate_internal_base_url("https://fultons-quiz.co.uk"),
            "https://fultons-quiz.co.uk",
        )

    def test_public_probe_rejects_file_url_before_opening_it(self) -> None:
        with patch("ops_monitor.build_opener") as build_opener:
            with self.assertRaises(ValueError):
                ops_monitor.probe_public_health("file:///C:/Windows/win.ini")
        build_opener.assert_not_called()

    def test_settings_token_is_write_only_preserved_and_saved_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            data_dir = base / "data"
            settings_path = data_dir / "local-ops-settings.json"
            ssh_root = base / ".ssh"
            ssh_root.mkdir()
            key_path = ssh_root / "ops_key"
            key_path.write_text("not-a-real-key", encoding="utf-8")

            with (
                patch.object(local_ops_settings, "DATA_DIR", data_dir),
                patch.object(local_ops_settings, "SETTINGS_PATH", settings_path),
                patch.object(local_ops_settings, "_ssh_root", return_value=ssh_root),
            ):
                payload = local_ops_settings.default_monitor_settings()
                payload["sshKeyPath"] = str(key_path)
                payload["internalQuizToken"] = "first-secret-token"
                response = local_ops_settings.save_monitor_settings(payload)

                self.assertEqual(response["internalQuizToken"], "")
                self.assertTrue(response["internalQuizTokenConfigured"])
                persisted = json.loads(settings_path.read_text(encoding="utf-8"))
                self.assertEqual(persisted["internalQuizToken"], "first-secret-token")

                response["internalQuizToken"] = ""
                second_response = local_ops_settings.save_monitor_settings(response)
                persisted_again = json.loads(settings_path.read_text(encoding="utf-8"))
                self.assertEqual(persisted_again["internalQuizToken"], "first-secret-token")
                self.assertEqual(second_response["internalQuizToken"], "")
                self.assertTrue(second_response["internalQuizTokenConfigured"])

                read_response = local_ops_settings.monitor_settings_response()
                serialized = json.dumps(read_response)
                self.assertNotIn("first-secret-token", serialized)
                self.assertFalse(list(data_dir.glob(".*.tmp")))
                if os.name != "nt":
                    self.assertEqual(
                        stat.S_IMODE(settings_path.stat().st_mode),
                        stat.S_IRUSR | stat.S_IWUSR,
                    )


class LocalOpsTransportSecurityTests(unittest.TestCase):
    def test_ssh_command_uses_option_terminator_and_revalidates_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ssh_root = Path(temp_dir) / ".ssh"
            ssh_root.mkdir()
            key_path = ssh_root / "ops_key"
            key_path.write_text("not-a-real-key", encoding="utf-8")
            config = monitor_config(ssh_key_path=str(key_path))
            with patch.object(local_ops_settings, "_ssh_root", return_value=ssh_root):
                command = ops_monitor.ssh_python_command(config, "payload")
                self.assertEqual(command[command.index("--") + 1], "ste@192.168.0.15")

                injected = monitor_config(
                    ssh_key_path=str(key_path),
                    ssh_target="-oProxyCommand=calc",
                )
                with self.assertRaises(ValueError):
                    ops_monitor.ssh_python_command(injected, "payload")

    def test_bearer_redirect_to_another_origin_is_rejected(self) -> None:
        request = Request(
            "https://fultons-quiz.co.uk/internal/ops-summary",
            headers={"Authorization": "Bearer test-secret-token"},
        )
        handler = ops_monitor.OriginPinnedRedirectHandler(
            ops_monitor.validate_internal_request_url
        )
        with self.assertRaises(HTTPError) as caught:
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                Message(),
                "https://attacker.example/collect",
            )
        self.assertEqual(caught.exception.code, 403)
        self.assertNotIn("test-secret-token", str(caught.exception))
        caught.exception.close()

    def test_noncanonical_final_url_is_rejected_and_response_is_closed(self) -> None:
        class UnexpectedResponse:
            headers = Message()

            def __init__(self) -> None:
                self.closed = False

            def geturl(self) -> str:
                return "file:///C:/Windows/win.ini"

            def close(self) -> None:
                self.closed = True

        response = UnexpectedResponse()
        opener = type("UnexpectedOpener", (), {"open": lambda *_args, **_kwargs: response})()
        request = Request(local_ops_settings.CANONICAL_PUBLIC_HEALTH_URL)
        with (
            patch("ops_monitor.build_opener", return_value=opener),
            self.assertRaises(HTTPError) as caught,
        ):
            ops_monitor._open_validated_url(
                request,
                timeout_sec=2,
                validator=local_ops_settings.validate_public_health_url,
            )
        self.assertEqual(caught.exception.code, 403)
        self.assertTrue(response.closed)
        caught.exception.close()

    def test_internal_request_rejects_ssrf_before_open_and_redacts_transport_errors(self) -> None:
        unsafe_config = monitor_config(internal_base_url="http://169.254.169.254")
        with patch("ops_monitor.build_opener") as build_opener:
            with self.assertRaises(RuntimeError):
                ops_monitor.internal_ops_request(
                    unsafe_config,
                    "/internal/ops-summary",
                    timeout_sec=2,
                )
        build_opener.assert_not_called()

        secret = "do-not-disclose-this-token"
        safe_config = monitor_config(internal_quiz_token=secret)
        with patch(
            "ops_monitor._open_validated_url",
            side_effect=URLError(f"upstream reflected {secret}"),
        ):
            with self.assertRaises(RuntimeError) as caught:
                ops_monitor.internal_ops_request(
                    safe_config,
                    "/internal/ops-summary",
                    timeout_sec=2,
                )
        self.assertNotIn(secret, str(caught.exception))
        self.assertIn("<redacted>", str(caught.exception))
        self.assertNotIn(secret, repr(safe_config))

    def test_internal_response_payload_is_scrubbed_of_configured_token(self) -> None:
        token = "response-secret-token"

        class FakeResponse:
            status = 200
            headers = Message()

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit: int) -> bytes:
                return json.dumps({"ok": True, "echo": token}).encode("utf-8")

        with patch("ops_monitor._open_validated_url", return_value=FakeResponse()):
            payload = ops_monitor.internal_ops_request(
                monitor_config(internal_quiz_token=token),
                "/internal/ops-summary",
                timeout_sec=2,
            )
        self.assertEqual(payload["echo"], "<redacted>")

    def test_quiz_actions_do_not_report_preserved_failed_replacements_as_success(self) -> None:
        blocked = {
            "date": "2026-08-16",
            "status": "published",
            "regeneration_failed": True,
            "regeneration_blocked": True,
            "regeneration_failure_reason": "Published quiz is immutable.",
        }
        config = monitor_config()
        with (
            patch(
                "ops_monitor.current_active_quiz_target",
                return_value=("2026-08-16", {}, "today"),
            ),
            patch("ops_monitor.internal_quiz_request", return_value=blocked),
        ):
            with self.assertRaisesRegex(RuntimeError, "immutable"):
                ops_monitor.generate_tomorrow_quiz_action(config)
            with self.assertRaisesRegex(RuntimeError, "immutable"):
                ops_monitor.regenerate_question_action(
                    config,
                    {
                        "date": "2026-08-16",
                        "subject": "football",
                        "difficulty": "easy",
                    },
                )


class LocalOpsQueueSecurityTests(unittest.TestCase):
    def test_bounded_executor_rejects_work_when_worker_and_queue_are_full(self) -> None:
        executor = ops_monitor.BoundedExecutor(
            max_workers=1,
            max_queue_size=1,
            thread_name_prefix="test-bounded-ops",
        )
        started = threading.Event()
        release = threading.Event()

        def blocking_work() -> str:
            started.set()
            release.wait(timeout=5)
            return "done"

        first = executor.submit(blocking_work)
        self.assertTrue(started.wait(timeout=2))
        second = executor.submit(blocking_work)
        with self.assertRaises(queue.Full):
            executor.submit(blocking_work)
        release.set()
        self.assertEqual(first.result(timeout=2), "done")
        self.assertEqual(second.result(timeout=2), "done")

    def test_action_flooding_is_limited_and_duplicate_jobs_are_reused(self) -> None:
        executor = HoldingExecutor()
        jobs: dict[str, dict[str, object]] = {}
        config = monitor_config()
        first_params = {
            "date": "2026-08-14",
            "subject": "general_knowledge",
            "difficulty": "easy",
        }
        second_params = {**first_params, "difficulty": "hard"}

        with (
            patch.object(ops_monitor.MonitorConfig, "from_env", return_value=config),
            patch.object(ops_monitor, "_LOCAL_ACTION_EXECUTOR", executor),
            patch.object(ops_monitor, "_LOCAL_ACTION_JOBS", jobs),
        ):
            first = ops_monitor.start_local_action_job("regenerate_question", first_params)
            duplicate = ops_monitor.start_local_action_job("regenerate_question", first_params)
            with self.assertRaises(RuntimeError):
                ops_monitor.start_local_action_job("regenerate_question", second_params)

        self.assertEqual(first["status"], "queued")
        self.assertTrue(duplicate["reused"])
        self.assertEqual(first["jobId"], duplicate["jobId"])
        self.assertEqual(len(executor.calls), 1)
        self.assertEqual(len(jobs), 1)


if __name__ == "__main__":
    unittest.main()

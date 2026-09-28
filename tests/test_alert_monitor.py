from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_DIR / "deploy" / "fultons-alert-monitor.py"
SPEC = importlib.util.spec_from_file_location("fultons_alert_monitor", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
monitor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = monitor
SPEC.loader.exec_module(monitor)


class AlertMonitorTests(unittest.TestCase):
    def test_alert_url_requires_https_without_credentials(self) -> None:
        self.assertEqual(
            monitor.validate_alert_url("https://ntfy.sh/private-topic"),
            "https://ntfy.sh/private-topic",
        )
        for value in (
            "http://ntfy.sh/topic",
            "https://user:password@example.com/topic",
            "not-a-url",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                monitor.validate_alert_url(value)

    def test_state_round_trip_is_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = Path(temp_dir) / "nested" / "state.json"
            monitor.write_state(state, ["second", "first"])
            self.assertEqual(monitor.read_state(state), ["first", "second"])

    def test_backup_check_verifies_recent_named_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old = root / "fultons-quiz-20260927T010000Z-aaaa0000"
            latest = root / "fultons-quiz-20260928T010000Z-bbbb0000"
            old.mkdir()
            latest.mkdir()
            (old / "manifest.json").write_text("{}", encoding="utf-8")
            (latest / "manifest.json").write_text(
                json.dumps({"createdAt": "2026-09-28T01:00:00Z"}),
                encoding="utf-8",
            )
            completed = monitor.subprocess.CompletedProcess([], 0, "", "")
            with (
                patch.object(
                    monitor,
                    "utc_now",
                    return_value=datetime(2026, 9, 28, 2, tzinfo=timezone.utc),
                ),
                patch.object(monitor, "run", return_value=completed) as run,
            ):
                self.assertIsNone(
                    monitor.backup_problem(root, Path("manager.py"), max_age_hours=36)
                )
            self.assertEqual(run.call_args.args[0][-1], str(latest))

    def test_backup_check_rejects_stale_backup_without_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backup = Path(temp_dir) / "fultons-quiz-20260920T010000Z-aaaa0000"
            backup.mkdir()
            (backup / "manifest.json").write_text(
                json.dumps({"createdAt": "2026-09-20T01:00:00Z"}),
                encoding="utf-8",
            )
            with (
                patch.object(
                    monitor,
                    "utc_now",
                    return_value=datetime(2026, 9, 28, 2, tzinfo=timezone.utc),
                ),
                patch.object(monitor, "run") as run,
            ):
                problem = monitor.backup_problem(
                    Path(temp_dir), Path("manager.py"), max_age_hours=36
                )
            self.assertIn("hours old", problem)
            run.assert_not_called()

    def test_units_use_private_environment_and_persistent_timer(self) -> None:
        service = (PROJECT_DIR / "deploy" / "fultons-alert.service").read_text()
        timer = (PROJECT_DIR / "deploy" / "fultons-alert.timer").read_text()
        self.assertIn("EnvironmentFile=%h/.config/fultons-alert.env", service)
        self.assertIn("NoNewPrivileges=true", service)
        self.assertIn("OnUnitActiveSec=5min", timer)
        self.assertIn("Persistent=true", timer)


if __name__ == "__main__":
    unittest.main()

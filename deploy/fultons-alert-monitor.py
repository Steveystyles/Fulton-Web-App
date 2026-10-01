#!/usr/bin/env python3
"""Send deduplicated operational alerts to a private HTTPS endpoint."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_STATE = Path.home() / ".local/state/fultons-alert/state.json"
DEFAULT_BACKUP_ROOT = Path("/srv/storage/backups/fultons-quiz")
DEFAULT_JELLYFIN_SUCCESS = Path.home() / ".local/state/jellyfin-backup/last-success"
DEFAULT_BACKUP_MANAGER = Path.home() / "fulton-web-app/deploy/backup_manager.py"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def container_problem(name: str, require_health: bool) -> str | None:
    result = run(
        [
            "docker",
            "inspect",
            "--format",
            "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}",
            name,
        ]
    )
    if result.returncode != 0:
        return f"{name} is unavailable"
    fields = result.stdout.strip().split()
    if not fields or fields[0] != "running":
        return f"{name} is not running"
    if require_health and (len(fields) < 2 or fields[1] != "healthy"):
        return f"{name} is not healthy"
    return None


def public_health_problem(url: str) -> str | None:
    try:
        parsed = urlparse(validate_alert_url(url))
        connection = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=15)
        try:
            connection.request(
                "GET",
                parsed.path or "/",
                headers={"User-Agent": "fultons-alert-monitor/1"},
            )
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                return "public health endpoint is unavailable"
            payload = json.loads(response.read())
        finally:
            connection.close()
    except Exception:
        return "public health endpoint is unavailable"
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return "public health endpoint reported failure"
    return None


def newest_backup(root: Path) -> Path | None:
    candidates = [
        path
        for path in root.glob("fultons-quiz-*")
        if path.is_dir() and (path / "manifest.json").is_file()
    ]
    return max(candidates, key=lambda path: path.name, default=None)


def backup_problem(root: Path, manager: Path, max_age_hours: float) -> str | None:
    latest = newest_backup(root)
    if latest is None:
        return "no Fulton backup is available"
    try:
        manifest = json.loads((latest / "manifest.json").read_text(encoding="utf-8"))
        created = datetime.fromisoformat(str(manifest["createdAt"]).replace("Z", "+00:00"))
        age_hours = (utc_now() - created.astimezone(timezone.utc)).total_seconds() / 3600
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return "latest Fulton backup manifest is invalid"
    if age_hours < 0 or age_hours > max_age_hours:
        return f"latest Fulton backup is {age_hours:.1f} hours old"
    result = run([sys.executable, str(manager), "verify", str(latest)], timeout=180)
    if result.returncode != 0:
        return "latest Fulton backup failed verification"
    return None


def freshness_problem(path: Path, max_age_hours: float, label: str) -> str | None:
    try:
        age_hours = (utc_now().timestamp() - path.stat().st_mtime) / 3600
    except OSError:
        return f"{label} success marker is missing"
    if age_hours < 0 or age_hours > max_age_hours:
        return f"{label} backup is {age_hours:.1f} hours old"
    return None


def smart_problem(lookback_minutes: int) -> str | None:
    result = run(
        [
            "journalctl",
            "--since",
            f"{lookback_minutes} minutes ago",
            "-u",
            "smartd.service",
            "-u",
            "smartmontools.service",
            "--no-pager",
            "-o",
            "cat",
        ]
    )
    if result.returncode != 0:
        return "SMART journal could not be checked"
    warning = re.compile(
        r"SMART.*(?:FAILED|failure)|(?:pending|uncorrectable) sectors?|"
        r"read failure|Device: .* (?:FAILED|unreadable)",
        re.IGNORECASE,
    )
    if warning.search(result.stdout):
        return "SMART reported a disk warning in the last 65 minutes"
    return None


def collect_problems(args: argparse.Namespace) -> list[str]:
    checks = [
        container_problem("fultons-quiz", require_health=True),
        container_problem("traefik", require_health=False),
        public_health_problem(args.health_url),
        backup_problem(args.backup_root, args.backup_manager, args.backup_max_age_hours),
        freshness_problem(
            args.jellyfin_success,
            args.jellyfin_max_age_hours,
            "Jellyfin",
        ),
        smart_problem(args.smart_lookback_minutes),
    ]
    return sorted(problem for problem in checks if problem)


def validate_alert_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("FULTONS_ALERT_URL must be an HTTPS URL without credentials")
    return value


def notify(url: str, title: str, message: str, priority: str, tags: str) -> None:
    parsed = urlparse(validate_alert_url(url))
    connection = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=20)
    try:
        connection.request(
            "POST",
            parsed.path or "/",
            body=message.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": priority,
                "Tags": tags,
                "User-Agent": "fultons-alert-monitor/1",
            },
        )
        response = connection.getresponse()
        response.read()
        if not 200 <= response.status < 300:
            raise RuntimeError(f"alert endpoint returned HTTP {response.status}")
    finally:
        connection.close()


def read_state(path: Path) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    problems = payload.get("problems") if isinstance(payload, dict) else None
    return sorted(item for item in problems if isinstance(item, str)) if isinstance(problems, list) else []


def write_state(path: Path, problems: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = json.dumps(
        {"checkedAt": utc_now().isoformat(), "problems": problems},
        sort_keys=True,
    )
    descriptor, temporary_name = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    parser.add_argument("--backup-manager", type=Path, default=DEFAULT_BACKUP_MANAGER)
    parser.add_argument("--jellyfin-success", type=Path, default=DEFAULT_JELLYFIN_SUCCESS)
    parser.add_argument("--health-url", default="https://fultons-quiz.co.uk/api/health")
    parser.add_argument("--backup-max-age-hours", type=float, default=36)
    parser.add_argument("--jellyfin-max-age-hours", type=float, default=192)
    parser.add_argument("--smart-lookback-minutes", type=int, default=65)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        alert_url = validate_alert_url(os.environ["FULTONS_ALERT_URL"])
    except (KeyError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    problems = collect_problems(args)
    previous = read_state(args.state)
    try:
        if args.test:
            message = "External alert delivery is working."
            if problems:
                message += " Current checks: " + "; ".join(problems)
            else:
                message += " All monitored checks are healthy."
            notify(alert_url, "Fulton's alert test", message, "default", "white_check_mark")
        elif problems != previous:
            if problems:
                notify(
                    alert_url,
                    "Fulton's service warning",
                    "; ".join(problems),
                    "high",
                    "warning",
                )
            elif previous:
                notify(
                    alert_url,
                    "Fulton's services recovered",
                    "All monitored checks are healthy again.",
                    "default",
                    "white_check_mark",
                )
        write_state(args.state, problems)
    except Exception as exc:
        print(f"alert delivery failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
SETTINGS_PATH = DATA_DIR / "local-ops-settings.json"


def _home_key_path() -> str:
    return str(Path.home() / ".ssh" / "codex_fultons_ed25519")


def _default_public_health_url() -> str:
    return "https://fultons-quiz.co.uk/api/health"


def _default_internal_base_url(public_health_url: str | None = None) -> str:
    raw = str(public_health_url or _default_public_health_url()).strip()
    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return "https://fultons-quiz.co.uk"


def default_monitor_settings() -> dict[str, Any]:
    public_health_url = _default_public_health_url()
    return {
        "cacheTtlSec": 15,
        "sshTarget": "ste@192.168.0.15",
        "sshPort": 22,
        "sshKeyPath": _home_key_path(),
        "sshConnectTimeoutSec": 6,
        "publicHealthUrl": public_health_url,
        "internalBaseUrl": _default_internal_base_url(public_health_url),
        "internalQuizToken": "",
        "composeFile": "/home/ste/fulton-web-app-deploy/compose.yaml",
        "envFile": "/srv/storage/appdata/fultons-quiz/app.env",
        "dataDir": "/srv/storage/appdata/fultons-quiz",
        "dbPath": "/srv/storage/appdata/fultons-quiz/fultons.db",
        "appPort": 3000,
    }


def _clamp_int(value: Any, default: int, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


def normalize_monitor_settings(raw: Any) -> dict[str, Any]:
    defaults = default_monitor_settings()
    if not isinstance(raw, dict):
        return defaults
    public_health_url = str(raw.get("publicHealthUrl") or defaults["publicHealthUrl"]).strip()
    internal_base_url = str(
        raw.get("internalBaseUrl") or _default_internal_base_url(public_health_url)
    ).strip()
    return {
        "cacheTtlSec": _clamp_int(raw.get("cacheTtlSec"), defaults["cacheTtlSec"], 5),
        "sshTarget": str(raw.get("sshTarget") or defaults["sshTarget"]).strip(),
        "sshPort": _clamp_int(raw.get("sshPort"), defaults["sshPort"], 1),
        "sshKeyPath": str(raw.get("sshKeyPath") or defaults["sshKeyPath"]).strip(),
        "sshConnectTimeoutSec": _clamp_int(
            raw.get("sshConnectTimeoutSec"),
            defaults["sshConnectTimeoutSec"],
            2,
        ),
        "publicHealthUrl": public_health_url,
        "internalBaseUrl": internal_base_url,
        "internalQuizToken": str(raw.get("internalQuizToken") or defaults["internalQuizToken"]).strip(),
        "composeFile": str(raw.get("composeFile") or defaults["composeFile"]).strip(),
        "envFile": str(raw.get("envFile") or defaults["envFile"]).strip(),
        "dataDir": str(raw.get("dataDir") or defaults["dataDir"]).strip(),
        "dbPath": str(raw.get("dbPath") or defaults["dbPath"]).strip(),
        "appPort": _clamp_int(raw.get("appPort"), defaults["appPort"], 1),
    }


def load_monitor_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return default_monitor_settings()
    try:
        payload = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_monitor_settings()
    return normalize_monitor_settings(payload)


def save_monitor_settings(raw: Any) -> dict[str, Any]:
    payload = normalize_monitor_settings(raw)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def monitor_settings_response() -> dict[str, Any]:
    return {
        "config": load_monitor_settings(),
        "settingsPath": str(SETTINGS_PATH),
    }

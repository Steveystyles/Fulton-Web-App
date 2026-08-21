from __future__ import annotations

import ipaddress
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
SETTINGS_PATH = DATA_DIR / "local-ops-settings.json"

CANONICAL_PUBLIC_HEALTH_URL = "https://fultons-quiz.co.uk/api/health"
CANONICAL_INTERNAL_HTTPS_ORIGINS = frozenset(
    {
        ("https", "fultons-quiz.co.uk", 443),
    }
)
LOOPBACK_INTERNAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
LOOPBACK_INTERNAL_PORTS = frozenset({3000, 8765})
ALLOWED_SSH_USERS = frozenset({"ste"})
ALLOWED_SSH_HOSTS = frozenset({"192.168.0.15"})

_SSH_USER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,31}\Z")
_VISIBLE_BEARER_RE = re.compile(r"[\x21-\x7e]{1,4096}\Z")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _ssh_root() -> Path:
    return Path.home() / ".ssh"


def _home_key_path() -> str:
    return str(_ssh_root() / "codex_fultons_ed25519")


def _default_public_health_url() -> str:
    return CANONICAL_PUBLIC_HEALTH_URL


def _default_internal_base_url(public_health_url: str | None = None) -> str:
    # The canonical HTTPS origin is explicitly trusted for the production-only
    # internal endpoints. Arbitrary hosts are rejected by validation below.
    del public_health_url
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


def _bounded_int(
    value: Any,
    default: int,
    *,
    minimum: int,
    maximum: int,
    field_name: str,
) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be an integer.") from error
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}.")
    return parsed


def _strict_text(value: Any, default: str, *, field_name: str, maximum: int = 4096) -> str:
    raw = default if value is None or value == "" else str(value)
    if raw != raw.strip():
        raise ValueError(f"{field_name} cannot have leading or trailing whitespace.")
    if not raw or len(raw) > maximum or _CONTROL_RE.search(raw):
        raise ValueError(f"{field_name} is invalid.")
    return raw


def validate_ssh_target(value: Any) -> str:
    target = _strict_text(value, "", field_name="sshTarget", maximum=128)
    if target.startswith("-") or any(character.isspace() for character in target):
        raise ValueError("sshTarget must be a known user@literal-host target.")
    if target.count("@") != 1:
        raise ValueError("sshTarget must use user@literal-host format.")
    user, host = target.split("@", 1)
    if not _SSH_USER_RE.fullmatch(user) or user not in ALLOWED_SSH_USERS:
        raise ValueError("sshTarget user is not allowed.")
    try:
        literal_host = ipaddress.ip_address(host)
    except ValueError as error:
        raise ValueError("sshTarget host must be an allowlisted literal IP address.") from error
    normalized_host = str(literal_host)
    if normalized_host not in ALLOWED_SSH_HOSTS:
        raise ValueError("sshTarget host is not allowed.")
    return f"{user}@{normalized_host}"


def _looks_like_windows_network_or_device_path(value: str) -> bool:
    windows_value = value.replace("/", "\\").casefold()
    return windows_value.startswith(("\\\\", "\\??\\", "\\device\\"))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _path_has_symlink_component(path: Path, root: Path) -> bool:
    current = path
    while True:
        try:
            is_junction = getattr(current, "is_junction", None)
            if current.is_symlink() or (callable(is_junction) and is_junction()):
                return True
        except OSError:
            return True
        if current == root:
            return False
        if current.parent == current:
            return True
        current = current.parent


def validate_ssh_key_path(
    value: Any,
    *,
    expected_root: Path | None = None,
    require_exists: bool = False,
) -> str:
    raw = _strict_text(value, "", field_name="sshKeyPath", maximum=1024)
    if _looks_like_windows_network_or_device_path(raw):
        raise ValueError("sshKeyPath cannot be a UNC, device, or network path.")

    key_path = Path(raw).expanduser()
    ssh_root = (expected_root or _ssh_root()).expanduser()
    if not key_path.is_absolute():
        raise ValueError("sshKeyPath must be an absolute path under the local .ssh directory.")

    lexical_root = Path(os.path.abspath(ssh_root))
    lexical_key = Path(os.path.abspath(key_path))
    if not _is_relative_to(lexical_key, lexical_root):
        raise ValueError("sshKeyPath must stay under the local .ssh directory.")
    if _path_has_symlink_component(lexical_key, lexical_root):
        raise ValueError("sshKeyPath cannot traverse a symbolic link.")

    try:
        resolved_root = lexical_root.resolve(strict=False)
        resolved_key = lexical_key.resolve(strict=False)
    except OSError as error:
        raise ValueError("sshKeyPath could not be resolved safely.") from error
    if not _is_relative_to(resolved_key, resolved_root):
        raise ValueError("sshKeyPath resolves outside the local .ssh directory.")
    if require_exists:
        if not resolved_key.is_file():
            raise ValueError(f"SSH key was not found at {resolved_key}.")
    return str(resolved_key)


def _parse_url(value: Any, *, field_name: str):
    raw = _strict_text(value, "", field_name=field_name, maximum=2048)
    if any(character.isspace() for character in raw):
        raise ValueError(f"{field_name} cannot contain whitespace.")
    try:
        parsed = urlparse(raw)
        # Accessing .port performs urllib's port range and syntax validation.
        _ = parsed.port
    except ValueError as error:
        raise ValueError(f"{field_name} is not a valid URL.") from error
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field_name} cannot contain credentials.")
    return raw, parsed


def validate_public_health_url(value: Any) -> str:
    raw, parsed = _parse_url(value, field_name="publicHealthUrl")
    if raw != CANONICAL_PUBLIC_HEALTH_URL:
        raise ValueError(
            f"publicHealthUrl must be the canonical {CANONICAL_PUBLIC_HEALTH_URL} endpoint."
        )
    if (
        parsed.scheme != "https"
        or parsed.hostname != "fultons-quiz.co.uk"
        or (parsed.port or 443) != 443
        or parsed.path != "/api/health"
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("publicHealthUrl is not an allowed health endpoint.")
    return CANONICAL_PUBLIC_HEALTH_URL


def validate_internal_base_url(value: Any) -> str:
    _raw, parsed = _parse_url(value, field_name="internalBaseUrl")
    scheme = parsed.scheme.casefold()
    host = (parsed.hostname or "").casefold()
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise ValueError("internalBaseUrl must contain only an allowed origin.")

    default_port = 443 if scheme == "https" else 80 if scheme == "http" else None
    port = parsed.port or default_port
    origin = (scheme, host, port)
    if origin in CANONICAL_INTERNAL_HTTPS_ORIGINS:
        return "https://fultons-quiz.co.uk"
    if scheme not in {"http", "https"} or host not in LOOPBACK_INTERNAL_HOSTS:
        raise ValueError("internalBaseUrl must use the canonical HTTPS host or loopback.")
    if port not in LOOPBACK_INTERNAL_PORTS:
        allowed_ports = ", ".join(str(item) for item in sorted(LOOPBACK_INTERNAL_PORTS))
        raise ValueError(f"internalBaseUrl loopback port must be one of: {allowed_ports}.")
    formatted_host = f"[{host}]" if ":" in host else host
    return f"{scheme}://{formatted_host}:{port}"


def validate_internal_quiz_token(value: Any) -> str:
    if value is None or value == "":
        return ""
    token = str(value)
    if token != token.strip() or not _VISIBLE_BEARER_RE.fullmatch(token):
        raise ValueError("internalQuizToken must be a single visible bearer-token value.")
    return token


def normalize_monitor_settings(
    raw: Any,
    *,
    existing_token: str = "",
    preserve_blank_token: bool = False,
) -> dict[str, Any]:
    defaults = default_monitor_settings()
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("Local ops settings must be a JSON object.")

    public_health_url = validate_public_health_url(
        raw.get("publicHealthUrl", defaults["publicHealthUrl"])
    )
    internal_base_url = validate_internal_base_url(
        raw.get("internalBaseUrl", _default_internal_base_url(public_health_url))
    )
    submitted_token = raw.get("internalQuizToken")
    if preserve_blank_token and (submitted_token is None or submitted_token == ""):
        internal_quiz_token = validate_internal_quiz_token(existing_token)
    else:
        internal_quiz_token = validate_internal_quiz_token(submitted_token)

    return {
        "cacheTtlSec": _bounded_int(
            raw.get("cacheTtlSec"),
            defaults["cacheTtlSec"],
            minimum=5,
            maximum=300,
            field_name="cacheTtlSec",
        ),
        "sshTarget": validate_ssh_target(raw.get("sshTarget", defaults["sshTarget"])),
        "sshPort": _bounded_int(
            raw.get("sshPort"),
            defaults["sshPort"],
            minimum=1,
            maximum=65535,
            field_name="sshPort",
        ),
        "sshKeyPath": validate_ssh_key_path(
            raw.get("sshKeyPath", defaults["sshKeyPath"])
        ),
        "sshConnectTimeoutSec": _bounded_int(
            raw.get("sshConnectTimeoutSec"),
            defaults["sshConnectTimeoutSec"],
            minimum=2,
            maximum=30,
            field_name="sshConnectTimeoutSec",
        ),
        "publicHealthUrl": public_health_url,
        "internalBaseUrl": internal_base_url,
        "internalQuizToken": internal_quiz_token,
        "composeFile": _strict_text(
            raw.get("composeFile"), defaults["composeFile"], field_name="composeFile"
        ),
        "envFile": _strict_text(raw.get("envFile"), defaults["envFile"], field_name="envFile"),
        "dataDir": _strict_text(raw.get("dataDir"), defaults["dataDir"], field_name="dataDir"),
        "dbPath": _strict_text(raw.get("dbPath"), defaults["dbPath"], field_name="dbPath"),
        "appPort": _bounded_int(
            raw.get("appPort"),
            defaults["appPort"],
            minimum=1,
            maximum=65535,
            field_name="appPort",
        ),
    }


def redact_monitor_settings(settings: dict[str, Any]) -> dict[str, Any]:
    payload = dict(settings)
    payload["internalQuizToken"] = ""
    payload["internalQuizTokenConfigured"] = bool(settings.get("internalQuizToken"))
    return payload


def load_monitor_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return default_monitor_settings()
    try:
        payload = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default_monitor_settings()
    return normalize_monitor_settings(payload)


def _atomic_write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path.parent, stat.S_IRWXU)
    except OSError:
        pass

    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        try:
            os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = -1
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def save_monitor_settings(raw: Any) -> dict[str, Any]:
    existing = load_monitor_settings()
    payload = normalize_monitor_settings(
        raw,
        existing_token=str(existing.get("internalQuizToken") or ""),
        preserve_blank_token=True,
    )
    _atomic_write_private_json(SETTINGS_PATH, payload)
    return redact_monitor_settings(payload)


def monitor_settings_response() -> dict[str, Any]:
    return {
        "config": redact_monitor_settings(load_monitor_settings()),
        "settingsPath": str(SETTINGS_PATH),
    }

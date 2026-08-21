from __future__ import annotations

import hmac
import os
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import local_ops_settings
import ops_monitor
import server


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
TOKEN_HEADER = "X-Fultons-Ops-Token"
TOKEN_FILE = Path(
    os.environ.get(
        "FULTONS_LOCAL_OPS_TOKEN_FILE",
        server.DATA_DIR / "local-ops-access-token",
    )
).expanduser()


def load_access_token(path: Path = TOKEN_FILE) -> str:
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(f"Local Ops access token could not be read from {path}.") from error
    if len(token) < 32 or len(token) > 256 or any(character.isspace() for character in token):
        raise RuntimeError("Local Ops access token must be a 32-256 character token.")
    return token


class LocalOpsHandler(server.FultonsHandler):
    """Isolated loopback handler exposing only Local Ops APIs and static assets."""

    ops_access_token = ""
    ops_port = DEFAULT_PORT

    def request_host_allowed(self) -> bool:
        raw_host = self.headers.get("Host", "").strip()
        if not raw_host:
            return False
        parsed = urlparse(f"//{raw_host}")
        hostname = (parsed.hostname or "").lower().rstrip(".")
        try:
            port = parsed.port or self.ops_port
        except ValueError:
            return False
        return hostname in {"127.0.0.1", "localhost", "::1"} and port == self.ops_port

    def request_origin_allowed(self) -> bool:
        origin = self.headers.get("Origin", "").strip()
        if not origin:
            return False
        parsed = urlparse(origin)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        try:
            port = parsed.port or 80
        except ValueError:
            return False
        return (
            parsed.scheme == "http"
            and hostname in {"127.0.0.1", "localhost", "::1"}
            and port == self.ops_port
            and not parsed.username
            and not parsed.password
            and parsed.path in {"", "/"}
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
        )

    def ops_request_authorized(self, method: str) -> bool:
        if not self.is_loopback_request() or not self.request_host_allowed():
            return False
        submitted = self.headers.get(TOKEN_HEADER, "")
        if not submitted or not hmac.compare_digest(submitted, self.ops_access_token):
            return False
        if method in {"POST", "PATCH", "DELETE"} and not self.request_origin_allowed():
            return False
        return True

    def route_api(self, method: str, path: str, query: str = "") -> None:
        if not path.startswith("/api/local/"):
            self.send_error_json(HTTPStatus.NOT_FOUND, "API route not found.")
            return
        if not self.ops_request_authorized(method):
            self.send_error_json(HTTPStatus.FORBIDDEN, "Local Ops authorization failed.")
            return

        params = parse_qs(query)
        if path == "/api/local/ops-monitor" and method == "GET":
            force = str(params.get("force", ["0"])[0]).strip().lower() in {
                "1",
                "true",
                "yes",
            }
            self.send_json(
                HTTPStatus.OK,
                ops_monitor.collect_dashboard_snapshot(force=force),
            )
            return

        if path == "/api/local/ops-config" and method == "GET":
            self.send_json(HTTPStatus.OK, local_ops_settings.monitor_settings_response())
            return

        if path == "/api/local/ops-config" and method == "POST":
            try:
                saved = local_ops_settings.save_monitor_settings(self.read_json())
            except ValueError as error:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
                return
            self.send_json(
                HTTPStatus.OK,
                {
                    "config": saved,
                    "settingsPath": str(local_ops_settings.SETTINGS_PATH),
                },
            )
            return

        if path == "/api/local/ops-action" and method == "POST":
            payload = self.read_json()
            action = str(payload.get("action") or "").strip()
            params_payload = payload.get("params")
            action_params = params_payload if isinstance(params_payload, dict) else None
            try:
                if ops_monitor.is_async_local_action(action):
                    self.send_json(
                        HTTPStatus.ACCEPTED,
                        ops_monitor.start_local_action_job(action, params=action_params),
                    )
                else:
                    self.send_json(
                        HTTPStatus.OK,
                        ops_monitor.run_local_action(action, params=action_params),
                    )
            except ValueError as error:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
            except RuntimeError as error:
                self.send_error_json(HTTPStatus.BAD_GATEWAY, str(error))
            return

        if path == "/api/local/ops-action-status" and method == "GET":
            job_id = str(params.get("jobId", [""])[0] or "").strip()
            try:
                self.send_json(HTTPStatus.OK, ops_monitor.get_local_action_job(job_id))
            except ValueError as error:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
            except LookupError as error:
                self.send_error_json(HTTPStatus.NOT_FOUND, str(error))
            return

        self.send_error_json(HTTPStatus.NOT_FOUND, "Local Ops route not found.")


def run() -> None:
    token = load_access_token()
    raw_port = os.environ.get("FULTONS_LOCAL_OPS_PORT", str(DEFAULT_PORT))
    try:
        port = int(raw_port)
    except ValueError as error:
        raise RuntimeError("FULTONS_LOCAL_OPS_PORT must be an integer.") from error
    if port < 1024 or port > 65535:
        raise RuntimeError("FULTONS_LOCAL_OPS_PORT must be between 1024 and 65535.")
    if not server.DIST_DIR.joinpath("index.html").is_file():
        raise RuntimeError("Frontend build is missing. Run npm run build first.")

    LocalOpsHandler.ops_access_token = token
    LocalOpsHandler.ops_port = port
    httpd = server.BoundedThreadingHTTPServer((DEFAULT_HOST, port), LocalOpsHandler)
    server.safe_log(f"Local Ops available only at http://{DEFAULT_HOST}:{port}/ops")
    httpd.serve_forever()


if __name__ == "__main__":
    run()

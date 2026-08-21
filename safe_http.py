from __future__ import annotations

import ipaddress
import socket
import ssl
from http.client import HTTPConnection, HTTPSConnection, HTTPException, HTTPResponse
from io import BytesIO
from email.message import Message
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit


DEFAULT_MAX_RESPONSE_BYTES = 2_000_000
DEFAULT_ALLOWED_PORTS = {80, 443}
MAX_REDIRECTS = 5


class UnsafeOutboundUrl(ValueError):
    """Raised when an outbound URL could reach a non-public network target."""


class ResponseTooLarge(ValueError):
    """Raised when an upstream response exceeds its endpoint-specific budget."""


def _normalized_hostname(url: str) -> tuple[str, int | None]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeOutboundUrl("Only http and https URLs are allowed.")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeOutboundUrl("Credentials are not allowed in outbound URLs.")
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        raise UnsafeOutboundUrl("Outbound URL has no hostname.")
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise UnsafeOutboundUrl("Outbound hostname is invalid.") from error
    try:
        port = parsed.port
    except ValueError as error:
        raise UnsafeOutboundUrl("Outbound URL has an invalid port.") from error
    return hostname, port


def _address_is_public(address: str) -> bool:
    value = ipaddress.ip_address(address.split("%", 1)[0])
    return value.is_global


def _validated_target(
    url: str,
    *,
    allowed_hosts: Iterable[str] | None,
    allowed_ports: Iterable[int],
) -> tuple[str, int, tuple[str, ...]]:
    hostname, explicit_port = _normalized_hostname(url)
    allowed_host_set = {
        value.strip().lower().rstrip(".").encode("idna").decode("ascii")
        for value in (allowed_hosts or ())
        if value.strip()
    }
    if allowed_host_set and hostname not in allowed_host_set:
        raise UnsafeOutboundUrl("Outbound hostname is not allowlisted.")

    parsed = urlsplit(url)
    effective_port = explicit_port or (443 if parsed.scheme == "https" else 80)
    if effective_port not in set(allowed_ports):
        raise UnsafeOutboundUrl("Outbound port is not allowed.")

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            answers = socket.getaddrinfo(
                hostname,
                effective_port,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as error:
            raise UnsafeOutboundUrl("Outbound hostname could not be resolved.") from error
        addresses = tuple(dict.fromkeys(str(answer[4][0]) for answer in answers if answer[4]))
    else:
        addresses = (str(literal),)
    if not addresses or any(not _address_is_public(address) for address in addresses):
        raise UnsafeOutboundUrl("Outbound hostname resolves to a non-public address.")
    return hostname, effective_port, addresses


def validate_public_http_url(
    url: str,
    *,
    allowed_hosts: Iterable[str] | None = None,
    allowed_ports: Iterable[int] = DEFAULT_ALLOWED_PORTS,
) -> str:
    """Validate scheme, destination port, DNS answers, and public routability."""
    _validated_target(
        url,
        allowed_hosts=allowed_hosts,
        allowed_ports=allowed_ports,
    )
    return url


class _PinnedHTTPConnection(HTTPConnection):
    def __init__(self, host: str, port: int, address: str, *, timeout: float) -> None:
        super().__init__(host, port=port, timeout=timeout)
        self._pinned_address = address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._pinned_address, self.port),
            self.timeout,
            self.source_address,
        )


class _PinnedHTTPSConnection(HTTPSConnection):
    def __init__(self, host: str, port: int, address: str, *, timeout: float) -> None:
        super().__init__(
            host,
            port=port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self._pinned_address = address

    def connect(self) -> None:
        sock = socket.create_connection(
            (self._pinned_address, self.port),
            self.timeout,
            self.source_address,
        )
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def read_bounded_response(
    response: HTTPResponse | HTTPError,
    *,
    max_bytes: int,
    label: str = "Upstream",
) -> tuple[bytes, str]:
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive.")
    headers = getattr(response, "headers", None) or Message()
    content_encoding = str(headers.get("Content-Encoding") or "identity").lower()
    if content_encoding not in {"", "identity"}:
        raise ResponseTooLarge(f"{label} compressed responses are not accepted.")
    raw_length = headers.get("Content-Length")
    if raw_length:
        try:
            declared_length = int(raw_length)
        except ValueError as error:
            raise ResponseTooLarge(f"{label} Content-Length is invalid.") from error
        if declared_length < 0 or declared_length > max_bytes:
            raise ResponseTooLarge(f"{label} response exceeds the allowed size.")
    body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ResponseTooLarge(f"{label} response exceeds the allowed size.")
    get_charset = getattr(headers, "get_content_charset", None)
    charset = (get_charset() if callable(get_charset) else None) or "utf-8"
    return body, charset


def _open_pinned_response(
    url: str,
    *,
    timeout: float,
    headers: dict[str, str],
    allowed_hosts: Iterable[str] | None,
    allowed_ports: Iterable[int],
) -> tuple[HTTPConnection, HTTPResponse]:
    hostname, port, addresses = _validated_target(
        url,
        allowed_hosts=allowed_hosts,
        allowed_ports=allowed_ports,
    )
    parsed = urlsplit(url)
    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"

    last_error: BaseException | None = None
    for address in addresses:
        connection: HTTPConnection
        if parsed.scheme == "https":
            connection = _PinnedHTTPSConnection(
                hostname,
                port,
                address,
                timeout=timeout,
            )
        else:
            connection = _PinnedHTTPConnection(
                hostname,
                port,
                address,
                timeout=timeout,
            )
        try:
            connection.request("GET", target, headers=headers)
            return connection, connection.getresponse()
        except (OSError, HTTPException) as error:
            last_error = error
            connection.close()
    raise URLError(last_error or "No public address was reachable.")


def fetch_public_bytes(
    url: str,
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
    max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    allowed_hosts: Iterable[str] | None = None,
    allowed_ports: Iterable[int] = DEFAULT_ALLOWED_PORTS,
) -> tuple[bytes, str]:
    """Fetch a bounded response using the exact public IPs that were validated."""
    if not float(timeout) > 0:
        raise ValueError("timeout must be positive.")
    allowed_host_values = tuple(allowed_hosts or ())
    allowed_port_values = tuple(allowed_ports)
    request_headers = {
        str(key): str(value)
        for key, value in (headers or {}).items()
        if str(key).lower() not in {"host", "content-length", "transfer-encoding"}
    }
    request_headers["Accept-Encoding"] = "identity"
    request_headers["Connection"] = "close"
    current_url = url

    for redirect_count in range(MAX_REDIRECTS + 1):
        connection, response = _open_pinned_response(
            current_url,
            timeout=timeout,
            headers=request_headers,
            allowed_hosts=allowed_host_values,
            allowed_ports=allowed_port_values,
        )
        try:
            location = response.headers.get("Location")
            if response.status in {301, 302, 303, 307, 308} and location:
                if redirect_count >= MAX_REDIRECTS:
                    raise HTTPError(
                        current_url,
                        response.status,
                        "Redirect limit exceeded.",
                        response.headers,
                        None,
                    )
                next_url = urljoin(current_url, str(location))
                current_origin = urlsplit(current_url)
                next_origin = urlsplit(next_url)
                if (
                    current_origin.scheme,
                    current_origin.hostname,
                    current_origin.port,
                ) != (
                    next_origin.scheme,
                    next_origin.hostname,
                    next_origin.port,
                ):
                    request_headers = {
                        key: value
                        for key, value in request_headers.items()
                        if key.lower() not in {"authorization", "cookie", "proxy-authorization"}
                    }
                current_url = next_url
                continue

            body, charset = read_bounded_response(
                response,
                max_bytes=max_bytes,
            )
            if response.status >= 400:
                raise HTTPError(
                    current_url,
                    response.status,
                    str(response.reason or "Upstream request failed."),
                    response.headers,
                    BytesIO(body),
                )
            return body, charset
        finally:
            response.close()
            connection.close()
    raise HTTPError(current_url, 508, "Redirect limit exceeded.", Message(), None)


def fetch_public_text(
    url: str,
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
    max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    allowed_hosts: Iterable[str] | None = None,
    allowed_ports: Iterable[int] = DEFAULT_ALLOWED_PORTS,
) -> str:
    body, charset = fetch_public_bytes(
        url,
        timeout=timeout,
        headers=headers,
        max_bytes=max_bytes,
        allowed_hosts=allowed_hosts,
        allowed_ports=allowed_ports,
    )
    return body.decode(charset, errors="replace")

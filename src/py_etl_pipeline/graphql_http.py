"""HTTP boundary for the optional, read-only GraphQL metadata probe."""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_REQUEST_BYTES = 64 * 1024
Headers = Sequence[tuple[bytes, bytes]]


class RequestRejected(Exception):
    """A public error containing no untrusted header or configuration values."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _single_header(headers: Headers, name: bytes) -> bytes | None:
    values = [value for key, value in headers if key.lower() == name]
    if len(values) > 1:
        raise RequestRejected(400, "Duplicate request header.")
    return values[0] if values else None


def _loopback(host: str) -> bool:
    if "%" in host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped.is_loopback
    return address.is_loopback


def _local_authority(value: bytes) -> tuple[str, str, int]:
    try:
        if any(character <= 32 or character >= 127 for character in value):
            raise ValueError
        parsed = urlsplit(value.decode("ascii"))
        _validate_authority_url(parsed, value)
        host = parsed.hostname or ""
        if host != "localhost" and not _loopback(host):
            raise ValueError
        _validate_authority_suffix(parsed.netloc, host)
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        if not 1 <= port <= 65535:
            raise ValueError
        return parsed.scheme, host, port
    except (UnicodeError, ValueError):
        raise RequestRejected(403, "A loopback or localhost authority is required.") from None


def _validate_authority_url(parsed, value: bytes) -> None:
    if parsed.scheme not in {"http", "https"} or parsed.username is not None:
        raise ValueError
    if parsed.path or parsed.query or parsed.fragment or b"?" in value or b"#" in value:
        raise ValueError


def _validate_authority_suffix(authority: str, host: str) -> None:
    expected_host = f"[{host}]" if ":" in host else host
    if not authority.lower().startswith(expected_host):
        raise ValueError
    suffix = authority[len(expected_host) :]
    if suffix and not (suffix.startswith(":") and suffix[1:].isascii() and suffix[1:].isdigit()):
        raise ValueError


def _require_local_request(scope: Scope) -> None:
    headers = scope.get("headers", [])
    if any(
        key.lower() == b"forwarded" or key.lower().startswith(b"x-forwarded-") for key, _ in headers
    ):
        raise RequestRejected(400, "Forwarding headers are not accepted in local mode.")
    peer = scope.get("client")
    if peer is None or not _loopback(peer[0]):
        raise RequestRejected(403, "Local mode requires a loopback connection.")
    site = _single_header(headers, b"sec-fetch-site")
    if site is not None and site not in {b"none", b"same-origin"}:
        raise RequestRejected(403, "Cross-origin requests are not permitted in local mode.")
    _require_local_origin(scope, headers)


def _require_local_origin(scope: Scope, headers: Headers) -> None:
    host = _single_header(headers, b"host")
    scheme = scope.get("scheme", "http")
    if host is None or scheme not in {"http", "https"}:
        raise RequestRejected(403, "A local request authority is required.")
    authority = _local_authority(scheme.encode("ascii") + b"://" + host)
    origin = _single_header(headers, b"origin")
    if origin is not None and _local_authority(origin) != authority:
        raise RequestRejected(403, "Cross-origin requests are not permitted in local mode.")


def _check_size_headers(scope: Scope) -> None:
    if len(scope.get("query_string", b"")) > MAX_REQUEST_BYTES:
        raise RequestRejected(414, "Query string exceeds the 64 KiB limit.")
    length = _single_header(scope.get("headers", []), b"content-length")
    if length is None:
        return
    if not length.isdigit() or len(length) > 20:
        raise RequestRejected(400, "Invalid Content-Length.")
    if int(length) > MAX_REQUEST_BYTES:
        raise RequestRejected(413, "Request body exceeds the 64 KiB limit.")


async def _read_body(receive: Receive, body: bytearray) -> bool:
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return False
        chunk = message.get("body", b"")
        if len(body) + len(chunk) > MAX_REQUEST_BYTES:
            raise RequestRejected(413, "Request body exceeds the 64 KiB limit.")
        body.extend(chunk)
        if not message.get("more_body", False):
            return True


def _replay_body(receive: Receive, body: bytearray) -> Receive:
    complete = False

    async def replay() -> Message:
        nonlocal complete
        if complete:
            return await receive()
        complete = True
        return {"type": "http.request", "body": bytes(body), "more_body": False}

    return replay


def _no_store(send: Send) -> Send:
    async def send_response(message: Message) -> None:
        if message["type"] == "http.response.start":
            message = dict(message)
            headers = [
                (key, value)
                for key, value in message.get("headers", [])
                if key.lower() != b"cache-control"
            ]
            message["headers"] = [*headers, (b"cache-control", b"no-store")]
        await send(message)

    return send_response


class GraphQLHTTPBoundary:
    """Restrict local access and bound input before Strawberry parses a request."""

    def __init__(self, app: ASGIApp, *, public_metadata: bool) -> None:
        self.app = app
        self.public_metadata = public_metadata

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = bytearray()
        try:
            if scope["method"] not in {"GET", "POST"}:
                raise RequestRejected(405, "Only GET and POST are supported.")
            if not self.public_metadata:
                _require_local_request(scope)
            _check_size_headers(scope)
            if await _read_body(receive, body):
                await self.app(scope, _replay_body(receive, body), _no_store(send))
        except RequestRejected as error:
            headers = {"Cache-Control": "no-store"}
            if error.status == 405:
                headers["Allow"] = "GET, POST"
            response = JSONResponse(
                {"detail": error.detail}, status_code=error.status, headers=headers
            )
            await response(scope, receive, send)
        finally:
            body.clear()

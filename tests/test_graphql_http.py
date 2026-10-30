"""Real ASGI routing and Strawberry parsing without sockets or a database."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from py_etl_pipeline.graphql_http import MAX_REQUEST_BYTES, GraphQLHTTPBoundary
from py_etl_pipeline.graphql_server import create_app


@pytest.fixture(autouse=True)
def local_default(monkeypatch):
    monkeypatch.delenv("ETL_GRAPHQL_PUBLIC", raising=False)


def _scope(*, peer=("127.0.0.1", 1234), headers=(), method="POST", path="/graphql", query=b""):
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": query,
        "headers": list(headers),
        "client": peer,
        "server": ("127.0.0.1", 8000),
    }


def _request(app, scope, *, chunks=(b"",), forbid_receive=False, disconnect=False):
    messages = deque(
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    )
    if disconnect:
        messages = deque([{"type": "http.disconnect"}])
    sent = []
    reads = 0

    async def receive():
        nonlocal reads
        reads += 1
        if forbid_receive:
            raise AssertionError("A rejected request reached body parsing")
        return messages.popleft() if messages else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    starts = [message for message in sent if message["type"] == "http.response.start"]
    return SimpleNamespace(
        status=starts[0]["status"] if starts else None,
        headers=dict(starts[0].get("headers", [])) if starts else {},
        body=b"".join(message.get("body", b"") for message in sent),
        reads=reads,
        sent=sent,
    )


def _json_request(app, *, peer=("127.0.0.1", 1234), extra_headers=()):
    headers = [(b"host", b"localhost:8000"), (b"content-type", b"application/json")]
    scope = _scope(peer=peer, headers=[*headers, *extra_headers])
    body = b'{"query":"{ health version etl { loadBatchSize defaultLoadMode scheduledDefault } }"}'
    return _request(app, scope, chunks=(body,))


def test_local_post_returns_only_the_metadata_schema(monkeypatch):
    monkeypatch.setenv("LOAD_BATCH_SIZE", "123")
    monkeypatch.setenv("LOAD_MODE", "upsert")
    monkeypatch.setenv("RUN_SCHEDULED", "true")
    result = _json_request(create_app())
    assert result.status == 200
    data = json.loads(result.body)["data"]
    assert set(data) == {"health", "version", "etl"}
    assert data["health"] == "ok" and isinstance(data["version"], str)
    assert data["etl"] == {
        "loadBatchSize": 123,
        "defaultLoadMode": "upsert",
        "scheduledDefault": True,
    }
    assert result.headers[b"cache-control"] == b"no-store"


def test_get_query_is_supported_and_graphql_ide_is_disabled():
    app = create_app()
    query = urlencode({"query": "{ health }"}).encode()
    result = _request(app, _scope(method="GET", query=query, headers=[(b"host", b"localhost")]))
    assert result.status == 200 and json.loads(result.body)["data"] == {"health": "ok"}
    result = _request(
        app, _scope(method="GET", headers=[(b"host", b"localhost"), (b"accept", b"text/html")])
    )
    assert result.status != 200
    assert b"graphiql" not in result.body.lower()


@pytest.mark.parametrize("path", ["/", "/other", "/graphql/", "/graphql/subpath"])
def test_only_the_exact_graphql_path_is_served(path):
    result = _request(create_app(), _scope(path=path), forbid_receive=True)
    assert result.status == 404


@pytest.mark.parametrize("method", ["PUT", "DELETE", "OPTIONS", "HEAD"])
def test_other_methods_are_rejected_before_body(method):
    result = _request(create_app(), _scope(method=method), forbid_receive=True)
    assert result.status == 405


def test_websocket_is_closed_without_accepting_or_reading():
    scope = _scope()
    scope["type"] = "websocket"
    scope["scheme"] = "ws"
    result = _request(create_app(), scope, forbid_receive=True)
    assert len(result.sent) == 1
    assert result.sent[0]["type"] == "websocket.close"


def test_asgi_lifespan_startup_and_shutdown_complete_without_services():
    events = deque([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])
    sent = []

    async def receive():
        return events.popleft()

    async def send(message):
        sent.append(message)

    asyncio.run(create_app()({"type": "lifespan", "asgi": {"version": "3.0"}}, receive, send))
    assert [event["type"] for event in sent] == [
        "lifespan.startup.complete",
        "lifespan.shutdown.complete",
    ]


@pytest.mark.parametrize("peer", [("198.51.100.1", 1234), ("localhost", 1234), None, ("::1%lo", 1)])
def test_local_default_rejects_nonliteral_or_remote_peers_before_body(peer):
    result = _request(
        create_app(), _scope(peer=peer, headers=[(b"host", b"localhost")]), forbid_receive=True
    )
    assert result.status == 403


@pytest.mark.parametrize("peer", [("::1", 1234), ("::ffff:127.0.0.1", 1234)])
def test_literal_ipv6_loopback_peers_are_supported(peer):
    assert _json_request(create_app(), peer=peer).status == 200


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"host", b"evil.example")],
        [(b"host", b"localhost.evil.example")],
        [(b"host", b"[::1]evil")],
        [(b"host", b"localhost:")],
        [(b"host", b"localhost"), (b"host", b"localhost")],
        [(b"host", b"localhost"), (b"origin", b"null")],
        [(b"host", b"localhost"), (b"origin", b"https://localhost")],
        [(b"host", b"localhost"), (b"origin", b"http://evil.example")],
        [(b"host", b"localhost"), (b"origin", b"http://localhost:8000")],
        [
            (b"host", b"localhost"),
            (b"origin", b"http://localhost"),
            (b"origin", b"http://localhost"),
        ],
        [(b"host", b"localhost"), (b"sec-fetch-site", b"cross-site")],
        [(b"host", b"localhost"), (b"sec-fetch-site", b"same-site")],
        [(b"host", b"localhost"), (b"sec-fetch-site", b"unknown")],
        [(b"host", b"localhost"), (b"sec-fetch-site", b"none"), (b"sec-fetch-site", b"none")],
    ],
)
def test_local_mode_rejects_unsafe_or_ambiguous_authority_and_origin(headers):
    result = _request(create_app(), _scope(headers=headers), forbid_receive=True)
    assert result.status in {400, 403}


@pytest.mark.parametrize("site", [b"none", b"same-origin"])
def test_local_matching_origin_and_fetch_metadata_are_allowed(site):
    headers = [(b"origin", b"http://localhost:8000"), (b"sec-fetch-site", site)]
    assert _json_request(create_app(), extra_headers=headers).status == 200


@pytest.mark.parametrize(
    "name", [b"forwarded", b"x-forwarded-for", b"X-Forwarded-Proto", b"x-forwarded-host"]
)
def test_forwarding_headers_are_rejected_locally(name):
    scope = _scope(headers=[(b"host", b"localhost"), (name, b"synthetic")])
    assert _request(create_app(), scope, forbid_receive=True).status == 400


def test_uvicorn_proxy_header_rewriting_cannot_turn_remote_access_into_local_access():
    app = ProxyHeadersMiddleware(create_app(), trusted_hosts="*")
    headers = [(b"host", b"localhost"), (b"x-forwarded-for", b"127.0.0.1")]
    result = _request(
        app, _scope(peer=("198.51.100.1", 1234), headers=headers), forbid_receive=True
    )
    assert result.status == 400


def test_public_opt_in_accepts_remote_metadata_without_using_forwarding_headers(monkeypatch):
    monkeypatch.setenv("ETL_GRAPHQL_PUBLIC", "1")
    headers = [(b"x-forwarded-for", b"invalid"), (b"origin", b"https://external.example")]
    result = _json_request(create_app(), peer=("198.51.100.1", 1234), extra_headers=headers)
    assert result.status == 200 and json.loads(result.body)["data"]["health"] == "ok"


@pytest.mark.parametrize("value", ["", "true", "yes", "2", " 1", "0\nFORGED_LINE"])
def test_invalid_public_mode_fails_without_reflecting_input(monkeypatch, value):
    monkeypatch.setenv("ETL_GRAPHQL_PUBLIC", value)
    with pytest.raises(ValueError, match="ETL_GRAPHQL_PUBLIC must be 0 or 1") as error:
        create_app()
    assert "FORGED_LINE" not in str(error.value)


def test_public_configuration_is_snapshotted_at_factory_creation(monkeypatch):
    app = create_app()
    monkeypatch.setenv("ETL_GRAPHQL_PUBLIC", "1")
    result = _request(
        app,
        _scope(peer=("198.51.100.1", 1234), headers=[(b"host", b"localhost")]),
        forbid_receive=True,
    )
    assert result.status == 403


@pytest.mark.parametrize(
    ("headers", "query", "status"),
    [
        ([(b"content-length", str(MAX_REQUEST_BYTES + 1).encode())], b"", 413),
        ([(b"content-length", b"-1")], b"", 400),
        ([(b"content-length", b"0"), (b"content-length", b"0")], b"", 400),
        ([], b"q" * (MAX_REQUEST_BYTES + 1), 414),
    ],
)
def test_input_limits_are_applied_before_body_and_graphql_parser(headers, query, status):
    scope = _scope(headers=[(b"host", b"localhost"), *headers], query=query)
    assert _request(create_app(), scope, forbid_receive=True).status == status


def test_chunked_body_limit_stops_before_calling_strawberry():
    async def forbidden_parser(scope, receive, send):
        raise AssertionError("Oversized data must not reach Strawberry")

    app = GraphQLHTTPBoundary(forbidden_parser, public_metadata=True)
    chunks = (b" " * MAX_REQUEST_BYTES, b"x", b"not read")
    result = _request(app, _scope(), chunks=chunks)
    assert result.status == 413 and result.reads == 2


def test_body_at_the_limit_and_split_across_chunks_is_preserved():
    data = b'{"query":"{ health }"}'
    data += b" " * (MAX_REQUEST_BYTES - len(data))
    headers = [(b"host", b"localhost"), (b"content-type", b"application/json")]
    result = _request(create_app(), _scope(headers=headers), chunks=(data[:100], data[100:]))
    assert result.status == 200 and json.loads(result.body)["data"] == {"health": "ok"}


def test_disconnected_upload_does_not_call_the_parser():
    async def forbidden_parser(scope, receive, send):
        raise AssertionError("Disconnected requests must not reach Strawberry")

    result = _request(
        GraphQLHTTPBoundary(forbidden_parser, public_metadata=True), _scope(), disconnect=True
    )
    assert result.sent == []

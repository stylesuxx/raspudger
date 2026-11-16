from __future__ import annotations

import http.client
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from rig_proxy.config import ProxyConfig
from rig_proxy.forwarding import UsageCap
from rig_proxy.server import make_server

_SSE_BODY = b'event: message\ndata: {"ok": true}\n\n'


class _FakeUpstream(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, handler: type[BaseHTTPRequestHandler]) -> None:
        super().__init__(("127.0.0.1", 0), handler)
        self.captured: list[dict[str, object]] = []


class _UpstreamHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def _record_and_reply(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        upstream: _FakeUpstream = self.server  # type: ignore[assignment]
        upstream.captured.append(
            {
                "path": self.path,
                "api_key": self.headers.get("x-api-key"),
                "authorization": self.headers.get("Authorization"),
                "body": body,
            }
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(_SSE_BODY)))
        self.end_headers()
        self.wfile.write(_SSE_BODY)

    do_POST = _record_and_reply
    do_GET = _record_and_reply


@contextmanager
def _proxy_against_fake(
    max_requests: int | None, auth_token: str | None = None
) -> Iterator[tuple[int, _FakeUpstream, UsageCap]]:
    upstream = _FakeUpstream(_UpstreamHandler)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    up_port = upstream.server_address[1]

    config = ProxyConfig(
        api_key="sk-ant-REAL",
        upstream_scheme="http",
        upstream_authority=f"127.0.0.1:{up_port}",
        port=0,
        max_requests=max_requests,
        auth_token=auth_token,
    )
    cap = UsageCap(max_requests)
    proxy = make_server(config, cap)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()

    try:
        yield proxy.server_address[1], upstream, cap
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()


def _post(
    port: int, path: str, body: bytes, api_key: str, bearer: str | None = None
) -> tuple[int, bytes]:
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("POST", path, body=body, headers=headers)
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def test_proxy_injects_real_key_and_forwards_body() -> None:
    with _proxy_against_fake(max_requests=None) as (port, upstream, _cap):
        status, data = _post(port, "/v1/messages", b'{"model":"x"}', api_key="placeholder")

    assert status == 200
    assert b"event: message" in data
    assert len(upstream.captured) == 1
    record = upstream.captured[0]
    assert record["path"] == "/v1/messages"
    assert record["api_key"] == "sk-ant-REAL"
    assert record["authorization"] is None
    assert record["body"] == b'{"model":"x"}'


def test_healthz_is_local_and_does_not_consume_cap() -> None:
    with _proxy_against_fake(max_requests=1) as (port, upstream, cap):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/healthz")
        response = conn.getresponse()
        health_status = response.status
        health_body = response.read()
        conn.close()

        assert health_status == 200
        assert health_body == b"ok"
        assert cap.count == 0
        assert upstream.captured == []


def test_request_cap_returns_429_past_the_ceiling() -> None:
    with _proxy_against_fake(max_requests=1) as (port, upstream, _cap):
        first_status, _ = _post(port, "/v1/messages", b"{}", api_key="placeholder")
        second_status, _ = _post(port, "/v1/messages", b"{}", api_key="placeholder")

    assert first_status == 200
    assert second_status == 429
    assert len(upstream.captured) == 1


def test_matching_bearer_token_is_authorized() -> None:
    with _proxy_against_fake(max_requests=None, auth_token="sekret") as (port, upstream, _cap):
        status, data = _post(port, "/v1/messages", b"{}", api_key="x", bearer="sekret")

    assert status == 200
    assert b"event: message" in data
    assert len(upstream.captured) == 1
    assert upstream.captured[0]["api_key"] == "sk-ant-REAL"


def test_wrong_or_missing_token_is_rejected_without_hitting_upstream() -> None:
    with _proxy_against_fake(max_requests=None, auth_token="sekret") as (port, upstream, cap):
        wrong_status, _ = _post(port, "/v1/messages", b"{}", api_key="x", bearer="nope")
        missing_status, _ = _post(port, "/v1/messages", b"{}", api_key="x")

    assert wrong_status == 401
    assert missing_status == 401
    assert upstream.captured == []
    assert cap.count == 0

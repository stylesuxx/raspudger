"""The proxy's HTTP server: a thin socket shell over the forwarding core.

One upstream connection per request, streamed back to the agent and delimited by
connection close, so both plain and ``text/event-stream`` responses pass through
without buffering. Concurrency is one thread per request.
"""

from __future__ import annotations

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast

from .config import ProxyConfig
from .forwarding import (
    UsageCap,
    build_upstream_headers,
    filter_response_headers,
    is_authorized,
)

BIND_HOST = "0.0.0.0"
HEALTH_PATH = "/healthz"
UPSTREAM_TIMEOUT_S = 600.0
STREAM_CHUNK_BYTES = 65536


class ProxyServer(ThreadingHTTPServer):
    """A threading HTTP server that carries the proxy config and request cap."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        config: ProxyConfig,
        cap: UsageCap,
    ) -> None:
        super().__init__(address, handler)
        self.config = config
        self.cap = cap


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_PUT(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()

    def do_PATCH(self) -> None:
        self._handle()

    def _handle(self) -> None:
        if self.path == HEALTH_PATH:
            self._respond_text(200, "ok")
            return

        server = cast(ProxyServer, self.server)
        body = self._read_body()

        if not is_authorized(self.headers.items(), server.config.auth_token):
            self._respond_text(401, "model proxy: unauthorized")
            return

        if not server.cap.try_acquire():
            self._respond_text(429, "model proxy request cap reached")
            return

        try:
            self._forward(server.config, body)
        except OSError as exc:
            self._respond_text(502, f"upstream error: {exc}")

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length > 0 else b""

    def _forward(self, config: ProxyConfig, body: bytes) -> None:
        headers = build_upstream_headers(self.headers.items(), config.api_key)
        connection = _open_upstream(config)
        try:
            connection.putrequest(self.command, self.path, skip_accept_encoding=True)
            for name, value in headers:
                connection.putheader(name, value)

            if body:
                connection.putheader("Content-Length", str(len(body)))

            connection.endheaders()

            if body:
                connection.send(body)

            response = connection.getresponse()
            self.send_response_only(response.status, response.reason)
            for name, value in filter_response_headers(response.getheaders()):
                self.send_header(name, value)

            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

            while True:
                chunk = response.read(STREAM_CHUNK_BYTES)
                if not chunk:
                    break

                self.wfile.write(chunk)
                self.wfile.flush()
        finally:
            connection.close()

    def _respond_text(self, status: int, message: str) -> None:
        payload = message.encode("utf-8")
        self.send_response_only(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        """Silence per-request access logging; the proxy is quiet by design."""


def _open_upstream(config: ProxyConfig) -> http.client.HTTPConnection:
    if config.upstream_scheme == "https":
        return http.client.HTTPSConnection(config.upstream_authority, timeout=UPSTREAM_TIMEOUT_S)

    return http.client.HTTPConnection(config.upstream_authority, timeout=UPSTREAM_TIMEOUT_S)


def make_server(config: ProxyConfig, cap: UsageCap) -> ProxyServer:
    """Build the proxy server bound to the configured port."""
    return ProxyServer((BIND_HOST, config.port), ProxyHandler, config, cap)

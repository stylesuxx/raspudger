"""Pure request/response shaping for the proxy, plus the request cap.

Kept free of sockets so it can be unit-tested directly: given the inbound
headers, produce the headers to send upstream (real key injected, inbound auth
and hop-by-hop headers removed), and given the upstream response headers, produce
the headers to return to the agent.
"""

from __future__ import annotations

import hmac
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field

# Hop-by-hop headers are connection-scoped and must not be forwarded (RFC 7230).
HOP_BY_HOP: frozenset[str] = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)

# Dropped from the inbound request: hop-by-hop, the host (the upstream client sets
# its own), the length (recomputed from the forwarded body), and any inbound auth
# the agent sent, which the real key replaces.
_STRIP_REQUEST: frozenset[str] = HOP_BY_HOP | {
    "host",
    "content-length",
    "x-api-key",
    "authorization",
}

# Dropped from the upstream response: hop-by-hop, plus the length so the proxy can
# stream the body and let the connection close delimit it.
_STRIP_RESPONSE: frozenset[str] = HOP_BY_HOP | {"content-length"}

API_KEY_HEADER = "x-api-key"


def presented_token(inbound_items: Iterable[tuple[str, str]]) -> str | None:
    """The caller's credential: the Authorization bearer, else the x-api-key value."""
    authorization: str | None = None
    api_key: str | None = None
    for name, value in inbound_items:
        lowered = name.lower()
        if lowered == "authorization":
            authorization = value
        elif lowered == "x-api-key":
            api_key = value

    if authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]

        return authorization

    return api_key


def is_authorized(inbound_items: Iterable[tuple[str, str]], expected_token: str | None) -> bool:
    """Whether the caller presented the session token the proxy expects.

    With no expected token the proxy is open (reachability is the only control);
    with one, the caller's token must match it in constant time.
    """
    if expected_token is None:
        return True

    token = presented_token(inbound_items)
    if token is None:
        return False

    return hmac.compare_digest(token, expected_token)


def build_upstream_headers(
    inbound_items: Iterable[tuple[str, str]], api_key: str
) -> list[tuple[str, str]]:
    """Headers to send upstream: inbound minus auth and hop-by-hop, real key added."""
    out = [(name, value) for name, value in inbound_items if name.lower() not in _STRIP_REQUEST]
    out.append((API_KEY_HEADER, api_key))
    return out


def filter_response_headers(
    upstream_items: Iterable[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Headers to return to the agent: upstream minus hop-by-hop and length."""
    return [(name, value) for name, value in upstream_items if name.lower() not in _STRIP_RESPONSE]


@dataclass
class UsageCap:
    """A thread-safe ceiling on how many requests the proxy will forward."""

    max_requests: int | None
    _count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def try_acquire(self) -> bool:
        """Count one request and return whether it is within the cap."""
        with self._lock:
            if self.max_requests is not None and self._count >= self.max_requests:
                return False

            self._count += 1
            return True

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

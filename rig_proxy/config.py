"""Proxy configuration, read from the environment.

The proxy runs in its own container with the real API key in its environment and
nothing else that matters. All settings come from ``RIG_PROXY_*`` variables plus
the ``ANTHROPIC_API_KEY`` it custodies.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from .errors import ProxyConfigError

DEFAULT_UPSTREAM = "https://api.anthropic.com"
DEFAULT_PORT = 8080


@dataclass(frozen=True)
class ProxyConfig:
    """Resolved proxy settings."""

    api_key: str
    upstream_scheme: str
    upstream_authority: str
    port: int
    max_requests: int | None
    auth_token: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> ProxyConfig:
        """Build the config from environment variables, or raise ProxyConfigError."""
        api_key = env.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise ProxyConfigError("ANTHROPIC_API_KEY is required for the model proxy")

        upstream = env.get("RIG_PROXY_UPSTREAM", "").strip() or DEFAULT_UPSTREAM
        scheme, authority = _split_upstream(upstream)

        port = _parse_int(env.get("RIG_PROXY_PORT", ""), DEFAULT_PORT, "RIG_PROXY_PORT")
        if not 1 <= port <= 65535:
            raise ProxyConfigError(f"RIG_PROXY_PORT out of range: {port}")

        max_requests_raw = env.get("RIG_PROXY_MAX_REQUESTS", "").strip()
        max_requests = (
            _parse_int(max_requests_raw, 0, "RIG_PROXY_MAX_REQUESTS") if max_requests_raw else None
        )
        if max_requests is not None and max_requests < 1:
            raise ProxyConfigError(f"RIG_PROXY_MAX_REQUESTS must be positive: {max_requests}")

        auth_token = env.get("RIG_PROXY_AUTH_TOKEN", "").strip() or None

        return cls(
            api_key=api_key,
            upstream_scheme=scheme,
            upstream_authority=authority,
            port=port,
            max_requests=max_requests,
            auth_token=auth_token,
        )


def _split_upstream(upstream: str) -> tuple[str, str]:
    """Split an upstream URL into its scheme and host[:port] authority."""
    parts = urlsplit(upstream)
    scheme = parts.scheme
    authority = parts.netloc
    if scheme not in ("http", "https"):
        raise ProxyConfigError(f"RIG_PROXY_UPSTREAM scheme must be http or https: {upstream!r}")

    if not authority:
        raise ProxyConfigError(f"RIG_PROXY_UPSTREAM has no host: {upstream!r}")

    return scheme, authority


def _parse_int(value: str, default: int, name: str) -> int:
    text = value.strip()
    if not text:
        return default
    try:
        return int(text)

    except ValueError as exc:
        raise ProxyConfigError(f"{name} must be an integer: {value!r}") from exc

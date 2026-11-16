from __future__ import annotations

from rig_proxy.forwarding import (
    UsageCap,
    build_upstream_headers,
    filter_response_headers,
    is_authorized,
    presented_token,
)


def test_build_upstream_headers_injects_real_key_and_drops_inbound_auth() -> None:
    inbound = [
        ("Host", "proxy:8080"),
        ("x-api-key", "placeholder"),
        ("Authorization", "Bearer placeholder"),
        ("Content-Type", "application/json"),
        ("anthropic-version", "2023-06-01"),
        ("Content-Length", "42"),
        ("Connection", "keep-alive"),
        ("transfer-encoding", "chunked"),
    ]

    result = build_upstream_headers(inbound, "sk-ant-real")
    names = {name.lower() for name, _ in result}

    assert ("x-api-key", "sk-ant-real") in result
    assert "placeholder" not in {value for _, value in result}
    assert "authorization" not in names
    assert "host" not in names
    assert "content-length" not in names
    assert "connection" not in names
    assert "transfer-encoding" not in names
    assert ("Content-Type", "application/json") in result
    assert ("anthropic-version", "2023-06-01") in result


def test_build_upstream_headers_preserves_duplicate_beta_headers() -> None:
    inbound = [
        ("anthropic-beta", "one"),
        ("anthropic-beta", "two"),
    ]
    result = build_upstream_headers(inbound, "k")
    betas = [value for name, value in result if name == "anthropic-beta"]
    assert betas == ["one", "two"]


def test_filter_response_headers_drops_hop_by_hop_and_length() -> None:
    upstream = [
        ("Content-Type", "text/event-stream"),
        ("Content-Length", "100"),
        ("Transfer-Encoding", "chunked"),
        ("request-id", "req_123"),
    ]
    result = filter_response_headers(upstream)
    names = {name.lower() for name, _ in result}
    assert "content-length" not in names
    assert "transfer-encoding" not in names
    assert ("Content-Type", "text/event-stream") in result
    assert ("request-id", "req_123") in result


def test_usage_cap_unlimited_when_none() -> None:
    cap = UsageCap(None)
    assert all(cap.try_acquire() for _ in range(1000))
    assert cap.count == 1000


def test_usage_cap_enforces_ceiling() -> None:
    cap = UsageCap(2)
    assert cap.try_acquire() is True
    assert cap.try_acquire() is True
    assert cap.try_acquire() is False
    assert cap.count == 2


def test_presented_token_prefers_bearer_authorization() -> None:
    assert presented_token([("Authorization", "Bearer abc123")]) == "abc123"


def test_presented_token_falls_back_to_x_api_key() -> None:
    assert presented_token([("x-api-key", "abc123")]) == "abc123"


def test_presented_token_none_when_absent() -> None:
    assert presented_token([("Content-Type", "application/json")]) is None


def test_is_authorized_open_when_no_expected_token() -> None:
    assert is_authorized([], None) is True


def test_is_authorized_accepts_matching_token() -> None:
    assert is_authorized([("Authorization", "Bearer secret")], "secret") is True


def test_is_authorized_rejects_wrong_or_missing_token() -> None:
    assert is_authorized([("Authorization", "Bearer nope")], "secret") is False
    assert is_authorized([], "secret") is False

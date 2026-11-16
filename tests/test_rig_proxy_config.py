from __future__ import annotations

import pytest

from rig_proxy.config import DEFAULT_PORT, ProxyConfig
from rig_proxy.errors import ProxyConfigError


def test_from_env_defaults() -> None:
    config = ProxyConfig.from_env({"ANTHROPIC_API_KEY": "sk-ant-real"})
    assert config.api_key == "sk-ant-real"
    assert config.upstream_scheme == "https"
    assert config.upstream_authority == "api.anthropic.com"
    assert config.port == DEFAULT_PORT
    assert config.max_requests is None


def test_from_env_custom_upstream_and_limits() -> None:
    config = ProxyConfig.from_env(
        {
            "ANTHROPIC_API_KEY": "sk-ant-real",
            "RIG_PROXY_UPSTREAM": "http://127.0.0.1:9000",
            "RIG_PROXY_PORT": "9100",
            "RIG_PROXY_MAX_REQUESTS": "5",
        }
    )
    assert config.upstream_scheme == "http"
    assert config.upstream_authority == "127.0.0.1:9000"
    assert config.port == 9100
    assert config.max_requests == 5


def test_missing_key_raises() -> None:
    with pytest.raises(ProxyConfigError):
        ProxyConfig.from_env({})
    with pytest.raises(ProxyConfigError):
        ProxyConfig.from_env({"ANTHROPIC_API_KEY": "   "})


def test_bad_upstream_scheme_raises() -> None:
    with pytest.raises(ProxyConfigError):
        ProxyConfig.from_env({"ANTHROPIC_API_KEY": "k", "RIG_PROXY_UPSTREAM": "ftp://host"})


def test_upstream_without_host_raises() -> None:
    with pytest.raises(ProxyConfigError):
        ProxyConfig.from_env({"ANTHROPIC_API_KEY": "k", "RIG_PROXY_UPSTREAM": "https:///path"})


def test_non_integer_port_raises() -> None:
    with pytest.raises(ProxyConfigError):
        ProxyConfig.from_env({"ANTHROPIC_API_KEY": "k", "RIG_PROXY_PORT": "abc"})


def test_port_out_of_range_raises() -> None:
    with pytest.raises(ProxyConfigError):
        ProxyConfig.from_env({"ANTHROPIC_API_KEY": "k", "RIG_PROXY_PORT": "70000"})


def test_non_positive_max_requests_raises() -> None:
    with pytest.raises(ProxyConfigError):
        ProxyConfig.from_env({"ANTHROPIC_API_KEY": "k", "RIG_PROXY_MAX_REQUESTS": "0"})


def test_auth_token_parsed_when_present() -> None:
    config = ProxyConfig.from_env({"ANTHROPIC_API_KEY": "k", "RIG_PROXY_AUTH_TOKEN": "sekret"})
    assert config.auth_token == "sekret"


def test_auth_token_none_when_absent() -> None:
    config = ProxyConfig.from_env({"ANTHROPIC_API_KEY": "k"})
    assert config.auth_token is None

from __future__ import annotations

from pathlib import Path

import pytest

from rig_mcp.config import RigConfig, RigConfigError


def minimal_env() -> dict[str, str]:
    return {
        "RIG_PI_HOST": "pi.local",
        "RIG_PIN_POWER": "17",
        "RIG_PIN_UART_TX": "14",
    }


def test_from_env_applies_defaults() -> None:
    config = RigConfig.from_env(minimal_env())
    assert config.pi_host == "pi.local"
    assert config.pi_user == "rig"
    assert config.pi_ssh_key is None
    assert config.pi_ssh_port == 22
    assert config.pi_known_hosts is None
    assert config.uart_host == "pi.local"
    assert config.uart_port == 5000
    assert config.pins.power == 17
    assert config.pins.uart_tx == 14
    assert config.pins.power_active_high is True
    assert config.state_root == Path("data/projects")
    assert config.uart_read_timeout == 0.1


def test_from_env_reads_overrides() -> None:
    env = minimal_env() | {
        "RIG_PI_USER": "operator",
        "RIG_PI_SSH_KEY": "/keys/rig",
        "RIG_PI_SSH_PORT": "2222",
        "RIG_PI_KNOWN_HOSTS": "/state/pi-known_hosts",
        "RIG_UART_HOST": "127.0.0.1",
        "RIG_UART_PORT": "5001",
        "RIG_POWER_ACTIVE_HIGH": "false",
        "RIG_STATE_ROOT": "/var/rig/state",
        "RIG_UART_READ_TIMEOUT": "0.5",
    }
    config = RigConfig.from_env(env)
    assert config.pi_user == "operator"
    assert config.pi_ssh_key == Path("/keys/rig")
    assert config.pi_ssh_port == 2222
    assert config.pi_known_hosts == Path("/state/pi-known_hosts")
    assert config.uart_host == "127.0.0.1"
    assert config.uart_port == 5001
    assert config.pins.power_active_high is False
    assert config.state_root == Path("/var/rig/state")
    assert config.uart_read_timeout == 0.5


def test_uart_host_defaults_to_pi_host() -> None:
    config = RigConfig.from_env(minimal_env())
    assert config.uart_host == config.pi_host


@pytest.mark.parametrize("missing", ["RIG_PI_HOST", "RIG_PIN_POWER", "RIG_PIN_UART_TX"])
def test_missing_required_setting_raises(missing: str) -> None:
    env = minimal_env()
    del env[missing]
    with pytest.raises(RigConfigError, match=missing):
        RigConfig.from_env(env)


def test_empty_required_setting_raises() -> None:
    env = minimal_env() | {"RIG_PI_HOST": ""}
    with pytest.raises(RigConfigError, match="RIG_PI_HOST"):
        RigConfig.from_env(env)


def test_non_integer_pin_raises() -> None:
    env = minimal_env() | {"RIG_PIN_POWER": "high"}
    with pytest.raises(RigConfigError, match="RIG_PIN_POWER"):
        RigConfig.from_env(env)


def test_unparseable_bool_raises() -> None:
    env = minimal_env() | {"RIG_POWER_ACTIVE_HIGH": "maybe"}
    with pytest.raises(RigConfigError, match="RIG_POWER_ACTIVE_HIGH"):
        RigConfig.from_env(env)

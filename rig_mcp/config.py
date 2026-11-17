"""Configuration for the live rig MCP server, loaded from the environment.

``RigConfig.from_env`` is pure: it reads a mapping and validates it, so tests
drive it with a plain dict and never touch the real environment, the network, or
the Pi. The entry point in ``main`` is the only place that reads ``os.environ``
and opens SSH/UART connections.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .ssh_transport import PinMap


class RigConfigError(ValueError):
    """A required setting is missing or malformed."""


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def _require(env: Mapping[str, str], key: str) -> str:
    value: str | None = env.get(key)
    if value is None or value == "":
        raise RigConfigError(f"missing required setting: {key}")

    return value


def _require_int(env: Mapping[str, str], key: str) -> int:
    raw: str = _require(env, key)
    try:
        return int(raw)
    except ValueError as error:
        raise RigConfigError(f"{key} must be an integer, got {raw!r}") from error


def _optional_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw: str | None = env.get(key)
    if raw is None or raw == "":
        return default

    try:
        return int(raw)
    except ValueError as error:
        raise RigConfigError(f"{key} must be an integer, got {raw!r}") from error


def _optional_int_or_none(env: Mapping[str, str], key: str) -> int | None:
    raw: str | None = env.get(key)
    if raw is None or raw == "":
        return None

    try:
        return int(raw)
    except ValueError as error:
        raise RigConfigError(f"{key} must be an integer, got {raw!r}") from error


def _optional_float(env: Mapping[str, str], key: str, default: float) -> float:
    raw: str | None = env.get(key)
    if raw is None or raw == "":
        return default

    try:
        return float(raw)
    except ValueError as error:
        raise RigConfigError(f"{key} must be a number, got {raw!r}") from error


def _optional_bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw: str | None = env.get(key)
    if raw is None or raw == "":
        return default

    lowered: str = raw.strip().lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False

    raise RigConfigError(f"{key} must be a boolean, got {raw!r}")


def _optional_str(env: Mapping[str, str], key: str) -> str | None:
    value: str | None = env.get(key)
    if value is None or value == "":
        return None

    return value


@dataclass(frozen=True)
class DutNetwork:
    """The isolated test network a WiFi-client DUT joins to reach the rig.

    The rig and the DUT share this subnet, so once a DUT joins it is reachable
    from the Pi for scanning. The PSK is a low-value credential for a disposable
    test network; it is exposed to the agent for onboarding.
    """

    ssid: str
    psk: str
    subnet: str | None
    iface: str | None


def _parse_dut_network(env: Mapping[str, str]) -> DutNetwork | None:
    ssid: str | None = _optional_str(env, "RIG_DUT_NET_SSID")
    if ssid is None:
        return None

    psk: str | None = _optional_str(env, "RIG_DUT_NET_PSK")
    if psk is None:
        raise RigConfigError("RIG_DUT_NET_PSK is required when RIG_DUT_NET_SSID is set")

    return DutNetwork(
        ssid=ssid,
        psk=psk,
        subnet=_optional_str(env, "RIG_DUT_NET_SUBNET"),
        iface=_optional_str(env, "RIG_DUT_NET_IFACE"),
    )


@dataclass(frozen=True)
class RigConfig:
    pi_host: str
    pi_user: str
    pi_ssh_key: Path | None
    pi_ssh_port: int
    pi_known_hosts: Path | None
    uart_host: str
    uart_port: int
    pins: PinMap
    state_root: Path
    uart_read_timeout: float
    device: str | None
    dut_network: DutNetwork | None

    @property
    def has_power(self) -> bool:
        """Whether a power relay is wired for this bench, so power tools apply."""
        return self.pins.power is not None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> RigConfig:
        pi_host: str = _require(env, "RIG_PI_HOST")
        key_raw: str | None = env.get("RIG_PI_SSH_KEY")
        known_hosts_raw: str | None = env.get("RIG_PI_KNOWN_HOSTS")
        pins = PinMap(
            uart_tx=_require_int(env, "RIG_PIN_UART_TX"),
            power=_optional_int_or_none(env, "RIG_PIN_POWER"),
            power_active_high=_optional_bool(env, "RIG_POWER_ACTIVE_HIGH", True),
        )

        return cls(
            pi_host=pi_host,
            pi_user=env.get("RIG_PI_USER") or "rig",
            pi_ssh_key=Path(key_raw) if key_raw else None,
            pi_ssh_port=_optional_int(env, "RIG_PI_SSH_PORT", 22),
            pi_known_hosts=Path(known_hosts_raw) if known_hosts_raw else None,
            uart_host=env.get("RIG_UART_HOST") or pi_host,
            uart_port=_optional_int(env, "RIG_UART_PORT", 5000),
            pins=pins,
            state_root=Path(env.get("RIG_STATE_ROOT") or "data/projects"),
            uart_read_timeout=_optional_float(env, "RIG_UART_READ_TIMEOUT", 0.1),
            device=_optional_str(env, "RIG_DEVICE"),
            dut_network=_parse_dut_network(env),
        )

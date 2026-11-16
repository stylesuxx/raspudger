"""Rig connection config for the agent container.

The rig's hardware tools are served inside the container by ``rig-mcp-server``,
which reads its settings from ``RIG_*`` environment variables (see
``rig_mcp.config``). This module turns the operator's rig config file plus a
``--rig-host`` override into the environment to inject and the files to mount:
the SSH key and known_hosts are host paths the operator names, remapped to fixed
container paths so the server inside finds them. The SSH key's bytes are mounted,
never passed as a value. The one credential that rides the environment is
``RIG_DUT_NET_PSK``, the test network's WiFi passphrase, which is low-value by
construction (a disposable test network) and is exposed to the agent for
onboarding.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import parse_env_file
from .errors import ConfigError, UsageError

CONTAINER_PI_KEY = "/rig/pi-key"
CONTAINER_KNOWN_HOSTS = "/rig/pi-known_hosts"

_REQUIRED = ("RIG_PI_HOST", "RIG_PIN_POWER", "RIG_PIN_UART_TX", "RIG_PI_SSH_KEY")


@dataclass(frozen=True)
class RigMount:
    host_path: Path
    container_path: str
    read_only: bool


@dataclass(frozen=True)
class RigLaunch:
    env: dict[str, str]
    mounts: list[RigMount]


def load_rig_launch(config_path: Path | None, host_override: str | None) -> RigLaunch | None:
    """Build the rig launch config, or None when no rig is configured.

    A rig is configured when the config file exists or ``--rig-host`` is given.
    Host-side key and known_hosts paths are remapped to container paths and
    returned as mounts. Missing required settings raise UsageError.
    """
    raw: dict[str, str] = {}
    if config_path is not None and config_path.exists():
        if not config_path.is_file():
            raise ConfigError(f"rig config is not a file: {config_path}")

        raw = {k: v for k, v in parse_env_file(config_path.read_text()).items()}

    if host_override is not None:
        raw["RIG_PI_HOST"] = host_override

    if not raw:
        return None

    missing = [key for key in _REQUIRED if not raw.get(key)]
    if missing:
        raise UsageError(f"rig config missing required settings: {', '.join(missing)}")

    env: dict[str, str] = {k: v for k, v in raw.items() if k.startswith("RIG_")}
    mounts: list[RigMount] = []

    key_host = Path(env["RIG_PI_SSH_KEY"])
    mounts.append(RigMount(key_host, CONTAINER_PI_KEY, read_only=True))
    env["RIG_PI_SSH_KEY"] = CONTAINER_PI_KEY

    known_hosts_host = env.get("RIG_PI_KNOWN_HOSTS")
    if known_hosts_host:
        mounts.append(RigMount(Path(known_hosts_host), CONTAINER_KNOWN_HOSTS, read_only=False))
        env["RIG_PI_KNOWN_HOSTS"] = CONTAINER_KNOWN_HOSTS

    return RigLaunch(env=env, mounts=mounts)

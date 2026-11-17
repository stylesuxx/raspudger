"""The read-only serial monitor: a live, decoupled view of the Pi's UART.

ser2net traces both directions of the line into one file in wire order. The
``rig-serial-monitor`` helper replays the recent tail of it and follows new data;
this module resolves the SSH target from the rig config, assembles the command
that runs the helper over SSH, and decides where a durable transcript is saved.
The stream is read-only, so it runs alongside a live agent session without
contending for the single-owner line.

Target resolution and save-path selection are pure functions over the rig config,
so tests drive them directly; the SSH subprocess and the terminal writes live in
the cli shell.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import parse_env_file
from .errors import UsageError

MONITOR_HELPER = "rig-serial-monitor"


@dataclass(frozen=True)
class MonitorTarget:
    """The SSH connection to the Pi that serves the monitor stream."""

    host: str
    user: str
    ssh_key: Path | None
    ssh_port: int
    known_hosts: Path | None

    @classmethod
    def from_rig_config(cls, config_path: Path, host_override: str | None) -> MonitorTarget:
        """Resolve the monitor target from the rig config and an optional host.

        Reads the same ``RIG_PI_*`` settings the agent session uses, so the
        monitor reaches the Pi over the same SSH identity. Raises UsageError when
        no host is configured or the SSH port is not an integer.
        """
        raw: dict[str, str] = {}
        if config_path.exists():
            if not config_path.is_file():
                raise UsageError(f"rig config is not a file: {config_path}")

            raw = dict(parse_env_file(config_path.read_text()))

        host = host_override or raw.get("RIG_PI_HOST")
        if not host:
            raise UsageError(
                "no Pi host for the monitor; set RIG_PI_HOST in the rig config or pass --rig-host"
            )

        port_raw = raw.get("RIG_PI_SSH_PORT")
        try:
            ssh_port = int(port_raw) if port_raw else 22
        except ValueError as error:
            raise UsageError(f"RIG_PI_SSH_PORT must be an integer, got {port_raw!r}") from error

        key = raw.get("RIG_PI_SSH_KEY")
        known_hosts = raw.get("RIG_PI_KNOWN_HOSTS")
        return cls(
            host=host,
            user=raw.get("RIG_PI_USER") or "rig",
            ssh_key=Path(key) if key else None,
            ssh_port=ssh_port,
            known_hosts=Path(known_hosts) if known_hosts else None,
        )


def build_monitor_command(target: MonitorTarget) -> list[str]:
    """The ssh argv that runs the read-only monitor helper on the Pi.

    Mirrors the agent's SSH options (batch mode, a dedicated known_hosts, and the
    rig key presented with IdentitiesOnly), so the monitor verifies the Pi the
    same way and never falls back to the operator's own keys.
    """
    argv = [
        "ssh",
        "-p",
        str(target.ssh_port),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "LogLevel=ERROR",
    ]
    if target.known_hosts is not None:
        argv += ["-o", f"UserKnownHostsFile={target.known_hosts}"]

    if target.ssh_key is not None:
        argv += ["-i", str(target.ssh_key), "-o", "IdentitiesOnly=yes"]

    argv += [f"{target.user}@{target.host}", "--", MONITOR_HELPER]
    return argv


def resolve_save_path(
    save: Path | None,
    no_save: bool,
    device: str | None,
    project_folder: Path,
    when: datetime,
) -> Path | None:
    """Where to write the durable transcript, or None to watch without saving.

    An explicit ``--save`` path wins. Otherwise a named device saves to a
    timestamped file in that device's project folder, since the Pi keeps only a
    small rolling buffer; ``--no-save`` or no device means watch only.
    """
    if save is not None:
        return save

    if no_save or device is None:
        return None

    return project_folder / device / f"uart-{when:%Y%m%d-%H%M%S}.log"

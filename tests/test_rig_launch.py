from __future__ import annotations

from pathlib import Path

import pytest

from raspudger.errors import UsageError
from raspudger.rig import CONTAINER_KNOWN_HOSTS, CONTAINER_PI_KEY, load_rig_launch


def write_rig_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "rig.env"
    path.write_text(body)
    return path


FULL = """
RIG_PI_HOST=pi.local
RIG_PI_USER=rig
RIG_PI_SSH_KEY=/keys/rig
RIG_PIN_POWER=17
RIG_PIN_UART_TX=14
RIG_POWER_ACTIVE_HIGH=false
"""


def test_no_config_and_no_host_means_no_rig(tmp_path: Path) -> None:
    assert load_rig_launch(tmp_path / "absent.env", None) is None


def test_full_config_builds_env_and_key_mount(tmp_path: Path) -> None:
    launch = load_rig_launch(write_rig_config(tmp_path, FULL), None)
    assert launch is not None
    assert launch.env["RIG_PI_HOST"] == "pi.local"
    assert launch.env["RIG_PIN_POWER"] == "17"
    assert launch.env["RIG_POWER_ACTIVE_HIGH"] == "false"
    # The host key path is remapped to the container path and mounted read-only.
    assert launch.env["RIG_PI_SSH_KEY"] == CONTAINER_PI_KEY
    key_mounts = [m for m in launch.mounts if m.container_path == CONTAINER_PI_KEY]
    assert len(key_mounts) == 1
    assert key_mounts[0].host_path == Path("/keys/rig")
    assert key_mounts[0].read_only is True


def test_host_override_wins(tmp_path: Path) -> None:
    launch = load_rig_launch(write_rig_config(tmp_path, FULL), "10.0.0.42")
    assert launch is not None
    assert launch.env["RIG_PI_HOST"] == "10.0.0.42"


def test_known_hosts_is_remapped_and_writable(tmp_path: Path) -> None:
    body = FULL + "RIG_PI_KNOWN_HOSTS=/state/pi-known_hosts\n"
    launch = load_rig_launch(write_rig_config(tmp_path, body), None)
    assert launch is not None
    assert launch.env["RIG_PI_KNOWN_HOSTS"] == CONTAINER_KNOWN_HOSTS
    kh = [m for m in launch.mounts if m.container_path == CONTAINER_KNOWN_HOSTS]
    assert len(kh) == 1
    assert kh[0].host_path == Path("/state/pi-known_hosts")
    assert kh[0].read_only is False


def test_only_rig_prefixed_keys_pass_through(tmp_path: Path) -> None:
    body = FULL + "UNRELATED=secret\n"
    launch = load_rig_launch(write_rig_config(tmp_path, body), None)
    assert launch is not None
    assert "UNRELATED" not in launch.env


@pytest.mark.parametrize("missing_line", ["RIG_PIN_POWER=17", "RIG_PI_SSH_KEY=/keys/rig"])
def test_missing_required_raises(tmp_path: Path, missing_line: str) -> None:
    body = "\n".join(line for line in FULL.strip().splitlines() if line != missing_line)
    with pytest.raises(UsageError, match="missing required"):
        load_rig_launch(write_rig_config(tmp_path, body), None)


def test_host_override_without_config_is_incomplete(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="missing required"):
        load_rig_launch(tmp_path / "absent.env", "10.0.0.42")

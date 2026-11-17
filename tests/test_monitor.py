from datetime import datetime
from pathlib import Path

import pytest

from raspudger.errors import UsageError
from raspudger.monitor import (
    CONSOLE_HELPER,
    MONITOR_HELPER,
    MonitorTarget,
    build_interactive_command,
    build_monitor_command,
    resolve_save_path,
)

RIG_CONFIG = (
    "RIG_PI_HOST=pi.local\n"
    "RIG_PI_USER=rig\n"
    "RIG_PI_SSH_KEY=/keys/rig\n"
    "RIG_PI_SSH_PORT=2222\n"
    "RIG_PI_KNOWN_HOSTS=/keys/known_hosts\n"
    "RIG_PIN_POWER=17\n"
)


def _write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "rig.env"
    path.write_text(text)
    return path


def test_target_from_rig_config(tmp_path: Path) -> None:
    target = MonitorTarget.from_rig_config(_write_config(tmp_path, RIG_CONFIG), None)
    assert target.host == "pi.local"
    assert target.user == "rig"
    assert target.ssh_key == Path("/keys/rig")
    assert target.ssh_port == 2222
    assert target.known_hosts == Path("/keys/known_hosts")


def test_target_defaults_user_and_port(tmp_path: Path) -> None:
    target = MonitorTarget.from_rig_config(_write_config(tmp_path, "RIG_PI_HOST=pi.local\n"), None)
    assert target.user == "rig"
    assert target.ssh_port == 22
    assert target.ssh_key is None
    assert target.known_hosts is None


def test_host_override_wins(tmp_path: Path) -> None:
    target = MonitorTarget.from_rig_config(_write_config(tmp_path, RIG_CONFIG), "other.local")
    assert target.host == "other.local"


def test_missing_host_raises(tmp_path: Path) -> None:
    with pytest.raises(UsageError):
        MonitorTarget.from_rig_config(_write_config(tmp_path, "RIG_PI_USER=rig\n"), None)


def test_missing_config_without_override_raises(tmp_path: Path) -> None:
    with pytest.raises(UsageError):
        MonitorTarget.from_rig_config(tmp_path / "absent.env", None)


def test_missing_config_with_override_resolves(tmp_path: Path) -> None:
    target = MonitorTarget.from_rig_config(tmp_path / "absent.env", "pi.local")
    assert target.host == "pi.local"
    assert target.ssh_port == 22


def test_bad_port_raises(tmp_path: Path) -> None:
    with pytest.raises(UsageError):
        MonitorTarget.from_rig_config(
            _write_config(tmp_path, "RIG_PI_HOST=pi.local\nRIG_PI_SSH_PORT=soon\n"), None
        )


def test_build_monitor_command_full(tmp_path: Path) -> None:
    target = MonitorTarget.from_rig_config(_write_config(tmp_path, RIG_CONFIG), None)
    argv = build_monitor_command(target)
    assert argv[0] == "ssh"
    assert argv[1:3] == ["-p", "2222"]
    assert "BatchMode=yes" in argv
    assert f"UserKnownHostsFile={Path('/keys/known_hosts')}" in argv
    assert "-i" in argv and str(Path("/keys/rig")) in argv
    assert "IdentitiesOnly=yes" in argv
    assert argv[-3:] == ["rig@pi.local", "--", MONITOR_HELPER]


def test_build_monitor_command_without_key(tmp_path: Path) -> None:
    target = MonitorTarget.from_rig_config(_write_config(tmp_path, "RIG_PI_HOST=pi.local\n"), None)
    argv = build_monitor_command(target)
    assert "-i" not in argv
    assert "IdentitiesOnly=yes" not in argv
    assert "UserKnownHostsFile" not in " ".join(argv)
    assert argv[-3:] == ["rig@pi.local", "--", MONITOR_HELPER]


def test_monitor_command_allocates_no_tty(tmp_path: Path) -> None:
    target = MonitorTarget.from_rig_config(_write_config(tmp_path, RIG_CONFIG), None)
    assert "-t" not in build_monitor_command(target)


def test_build_interactive_command(tmp_path: Path) -> None:
    target = MonitorTarget.from_rig_config(_write_config(tmp_path, RIG_CONFIG), None)
    argv = build_interactive_command(target, None)
    assert argv[0] == "ssh"
    assert "-t" in argv  # a PTY for the terminal
    assert "-i" in argv and str(Path("/keys/rig")) in argv
    assert argv[-4:] == ["rig@pi.local", "--", "sudo", CONSOLE_HELPER]


def test_interactive_command_passes_baud(tmp_path: Path) -> None:
    target = MonitorTarget.from_rig_config(_write_config(tmp_path, RIG_CONFIG), None)
    argv = build_interactive_command(target, 9600)
    assert argv[-5:] == ["rig@pi.local", "--", "sudo", CONSOLE_HELPER, "9600"]


def test_resolve_save_path_defaults_to_device_folder() -> None:
    when = datetime(2026, 11, 17, 14, 30, 22)
    path = resolve_save_path(None, False, "esp32", Path("data/projects"), when)
    assert path == Path("data/projects/esp32/uart-20261117-143022.log")


def test_resolve_save_path_explicit_wins() -> None:
    path = resolve_save_path(
        Path("/tmp/out.log"), False, "esp32", Path("data/projects"), datetime.now()
    )
    assert path == Path("/tmp/out.log")


def test_resolve_save_path_no_save() -> None:
    assert resolve_save_path(None, True, "esp32", Path("data/projects"), datetime.now()) is None


def test_resolve_save_path_without_device() -> None:
    assert resolve_save_path(None, False, None, Path("data/projects"), datetime.now()) is None

from pathlib import Path

import pytest

from raspudger.args import (
    AGENT_HOME_ROOT,
    DEFAULT_CONFIG,
    DEFAULT_PROJECT_FOLDER,
    DEFAULT_RIG_CONFIG,
    default_agent_home,
    parse_args,
    parse_monitor_args,
    prepare_paths,
)
from raspudger.errors import UsageError


def test_parses_explicit_flags(tmp_path: Path) -> None:
    config = tmp_path / "creds.env"
    config.write_text("placeholder")
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    args = parse_args(
        [
            "--agent",
            "claude",
            "--config",
            str(config),
            "--project-folder",
            str(project),
            "--agent-home",
            str(home),
        ]
    )
    assert args.agent == "claude"
    assert args.config == config
    assert args.project_folder == project
    assert args.agent_home == home
    assert args.login is False
    assert args.project_folder_defaulted is False
    assert args.task is None
    assert args.is_interactive is True


def test_defaults_when_omitted() -> None:
    args = parse_args(["--agent", "claude"])
    assert args.config == DEFAULT_CONFIG
    assert args.project_folder == DEFAULT_PROJECT_FOLDER
    assert args.agent_home == AGENT_HOME_ROOT / "claude"
    assert args.project_folder_defaulted is True
    assert args.login is False


def test_agent_home_is_per_agent() -> None:
    assert default_agent_home("kimi") == AGENT_HOME_ROOT / "kimi"
    assert parse_args(["--agent", "kimi"]).agent_home == AGENT_HOME_ROOT / "kimi"


def test_data_dir_sets_base(tmp_path: Path) -> None:
    base = tmp_path / "state"
    args = parse_args(["--agent", "claude", "--data-dir", str(base)])
    assert args.project_folder == base / "projects"
    assert args.agent_home == base / "agent-home" / "claude"


def test_task_switches_to_headless() -> None:
    args = parse_args(["--agent", "claude", "--task", "what is your purpose"])
    assert args.task == "what is your purpose"
    assert args.effective_task == "what is your purpose"
    assert args.is_interactive is False


def test_login_forces_interactive_over_task() -> None:
    args = parse_args(["--agent", "claude", "--login", "--task", "ignored"])
    assert args.login is True
    assert args.effective_task is None
    assert args.is_interactive is True


def test_missing_agent_exits() -> None:
    with pytest.raises(SystemExit):
        parse_args([])


def test_prepare_creates_project_and_home_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    args = parse_args(["--agent", "claude"])
    prepare_paths(args)
    assert (tmp_path / DEFAULT_PROJECT_FOLDER).is_dir()
    assert (tmp_path / AGENT_HOME_ROOT / "claude").is_dir()


def test_prepare_accepts_existing_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    args = parse_args(
        [
            "--agent",
            "claude",
            "--project-folder",
            str(project),
            "--agent-home",
            str(tmp_path / "home"),
        ]
    )
    prepare_paths(args)
    assert (tmp_path / "home").is_dir()


def test_prepare_rejects_missing_explicit_project(tmp_path: Path) -> None:
    args = parse_args(
        [
            "--agent",
            "claude",
            "--project-folder",
            str(tmp_path / "missing"),
            "--agent-home",
            str(tmp_path / "home"),
        ]
    )
    with pytest.raises(UsageError):
        prepare_paths(args)


def test_prepare_rejects_non_directory_project(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "afile"
    not_a_dir.write_text("placeholder")
    args = parse_args(
        [
            "--agent",
            "claude",
            "--project-folder",
            str(not_a_dir),
            "--agent-home",
            str(tmp_path / "home"),
        ]
    )
    with pytest.raises(UsageError):
        prepare_paths(args)


def test_rig_config_defaults_and_host_none() -> None:
    from raspudger.args import DEFAULT_RIG_CONFIG

    args = parse_args(["--agent", "claude"])
    assert args.rig_config == DEFAULT_RIG_CONFIG
    assert args.rig_host is None


def test_rig_flags_parsed() -> None:
    args = parse_args(
        ["--agent", "claude", "--rig-config", "/etc/rig.env", "--rig-host", "10.0.0.5"]
    )
    assert args.rig_config == Path("/etc/rig.env")
    assert args.rig_host == "10.0.0.5"


def test_network_defaults_none_and_parses() -> None:
    assert parse_args(["--agent", "claude"]).network is None
    assert parse_args(["--agent", "claude", "--network", "netx"]).network == "netx"


def test_device_defaults_none_and_parses() -> None:
    assert parse_args(["--agent", "claude"]).device is None
    assert parse_args(["--agent", "claude", "--device", "router-a"]).device == "router-a"


def test_no_power_defaults_false_and_parses() -> None:
    assert parse_args(["--agent", "claude"]).no_power is False
    assert parse_args(["--agent", "claude", "--no-power"]).no_power is True


def test_permission_mode_defaults_to_bypass_and_overrides() -> None:
    from raspudger.args import DEFAULT_PERMISSION_MODE

    assert parse_args(["--agent", "claude"]).permission_mode == DEFAULT_PERMISSION_MODE
    assert parse_args(["--agent", "claude"]).permission_mode == "bypassPermissions"
    over = parse_args(["--agent", "claude", "--permission-mode", "default"])
    assert over.permission_mode == "default"


def test_parse_monitor_defaults() -> None:
    monitor = parse_monitor_args([])
    assert monitor.rig_config == DEFAULT_RIG_CONFIG
    assert monitor.rig_host is None
    assert monitor.interactive is False
    assert monitor.baud is None
    assert monitor.device is None
    assert monitor.project_folder == DEFAULT_PROJECT_FOLDER
    assert monitor.save is None
    assert monitor.no_save is False


def test_parse_monitor_options() -> None:
    monitor = parse_monitor_args(
        [
            "--rig-config",
            "custom.env",
            "--rig-host",
            "pi.local",
            "--device",
            "esp32",
            "--save",
            "out.log",
            "--no-save",
            "--interactive",
            "--baud",
            "9600",
        ]
    )
    assert monitor.rig_config == Path("custom.env")
    assert monitor.rig_host == "pi.local"
    assert monitor.device == "esp32"
    assert monitor.save == Path("out.log")
    assert monitor.no_save is True
    assert monitor.interactive is True
    assert monitor.baud == 9600

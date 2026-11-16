import json
from pathlib import Path

from raspudger.adapters import resolve_adapter
from raspudger.args import parse_args
from raspudger.config import Credential
from raspudger.invocation import DockerInvocation, build_docker_command
from raspudger.rig import CONTAINER_PI_KEY, load_rig_launch

IMAGE = "raspudger-agent:latest"


def _rig_launch(tmp_path: Path):
    config = tmp_path / "rig.env"
    config.write_text(
        "RIG_PI_HOST=pi.local\nRIG_PI_SSH_KEY=/keys/rig\nRIG_PIN_POWER=17\nRIG_PIN_UART_TX=14\n"
    )
    return load_rig_launch(config, None)


def _mcp_config_from_argv(argv: list[str]) -> dict:
    index = argv.index("--mcp-config")
    return json.loads(argv[index + 1])


def _build(
    tmp_path: Path,
    task: str | None = None,
    credential: Credential | None = None,
    login: bool = False,
) -> tuple[DockerInvocation, Path, Path]:
    config = tmp_path / "config.env"
    config.write_text("placeholder")
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    argv = [
        "--agent",
        "claude",
        "--config",
        str(config),
        "--project-folder",
        str(project),
        "--agent-home",
        str(home),
    ]
    if task is not None:
        argv += ["--task", task]
    if login:
        argv += ["--login"]
    invocation = build_docker_command(
        args=parse_args(argv),
        adapter=resolve_adapter("claude"),
        credential=credential,
        image=IMAGE,
    )
    return invocation, project, home


def test_builds_docker_run(tmp_path: Path) -> None:
    invocation, project, _auth = _build(tmp_path)
    assert invocation.argv[:3] == ["docker", "run", "--rm"]
    assert IMAGE in invocation.argv
    assert f"{project.resolve()}:/rig/work" in invocation.argv
    assert "-w" in invocation.argv
    assert "/rig/work" in invocation.argv
    assert "claude" in invocation.argv


def test_mounts_agent_home_and_sets_config_dir(tmp_path: Path) -> None:
    invocation, _project, home = _build(tmp_path)
    assert f"{home.resolve()}:/agent-home" in invocation.argv
    assert "CLAUDE_CONFIG_DIR=/agent-home" in invocation.argv


def test_no_rig_means_no_mcp_config(tmp_path: Path) -> None:
    invocation, _project, _home = _build(tmp_path)
    assert "--mcp-config" not in invocation.argv


def test_rig_mounts_key_and_registers_mcp_server(tmp_path: Path) -> None:
    config = tmp_path / "config.env"
    config.write_text("placeholder")
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    argv = parse_args(
        [
            "--agent",
            "claude",
            "--config",
            str(config),
            "--project-folder",
            str(project),
            "--agent-home",
            str(home),
            "--task",
            "scan",
        ]
    )
    invocation = build_docker_command(
        args=argv,
        adapter=resolve_adapter("claude"),
        credential=None,
        image=IMAGE,
        rig=_rig_launch(tmp_path),
    )
    assert f"{Path('/keys/rig').resolve()}:{CONTAINER_PI_KEY}:ro" in invocation.argv
    assert "--strict-mcp-config" in invocation.argv
    config_json = _mcp_config_from_argv(invocation.argv)
    server = config_json["mcpServers"]["rig"]
    assert server["command"] == "rig-mcp-server"
    assert server["env"]["RIG_PI_HOST"] == "pi.local"
    assert server["env"]["RIG_PI_SSH_KEY"] == CONTAINER_PI_KEY
    # The strict flag precedes -p so the task still runs headless.
    assert invocation.argv[-2:] == ["-p", "scan"]


def test_interactive_adds_tty(tmp_path: Path) -> None:
    invocation, _project, _auth = _build(tmp_path)
    assert "-it" in invocation.argv


def test_headless_has_no_tty_and_prints(tmp_path: Path) -> None:
    invocation, _project, _auth = _build(tmp_path, task="hello")
    assert "-it" not in invocation.argv
    assert "-p" in invocation.argv


def test_login_is_interactive_over_task(tmp_path: Path) -> None:
    invocation, _project, _auth = _build(tmp_path, task="ignored", login=True)
    assert "-it" in invocation.argv
    assert "-p" not in invocation.argv


def test_no_credential_injects_no_secret(tmp_path: Path) -> None:
    invocation, _project, _auth = _build(tmp_path, credential=None)
    assert invocation.env == {}


def test_credential_in_env_never_in_argv(tmp_path: Path) -> None:
    credential = Credential(env_var="CLAUDE_CODE_OAUTH_TOKEN", value="sk-secret-xyz")
    invocation, _project, _auth = _build(tmp_path, credential=credential)
    assert "CLAUDE_CODE_OAUTH_TOKEN" in invocation.argv
    assert "sk-secret-xyz" not in " ".join(invocation.argv)
    assert invocation.env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-secret-xyz"


def test_network_flag_passed_through(tmp_path: Path) -> None:
    config = tmp_path / "config.env"
    config.write_text("x")
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()
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
            "--network",
            "raspudger_default",
        ]
    )
    invocation = build_docker_command(
        args=args, adapter=resolve_adapter("claude"), credential=None, image=IMAGE
    )
    i = invocation.argv.index("--network")
    assert invocation.argv[i + 1] == "raspudger_default"


def test_no_network_flag_by_default(tmp_path: Path) -> None:
    invocation, _p, _h = _build(tmp_path)
    assert "--network" not in invocation.argv


def test_default_run_sets_bypass_permission_mode(tmp_path: Path) -> None:
    invocation, _p, _h = _build(tmp_path)
    i = invocation.argv.index("--permission-mode")
    assert invocation.argv[i + 1] == "bypassPermissions"

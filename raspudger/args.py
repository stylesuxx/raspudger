"""Command-line argument parsing, defaults, and path preparation."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .errors import UsageError

# All user-managed runtime state lives under one directory, gitignored.
DEFAULT_DATA_DIR = Path("data")
DEFAULT_PROJECT_FOLDER = DEFAULT_DATA_DIR / "projects"
# The agent home holds one subdirectory per agent, so agents never collide.
AGENT_HOME_ROOT = DEFAULT_DATA_DIR / "agent-home"
DEFAULT_CONFIG = Path("config.env")
# Rig connection settings (host, key, pins); host-specific, so gitignored.
DEFAULT_RIG_CONFIG = Path("rig.env")
# The container is the sandbox boundary, so the agent runs its tools without
# per-call approval prompts by default; override with --permission-mode.
DEFAULT_PERMISSION_MODE = "bypassPermissions"


def default_agent_home(agent: str) -> Path:
    """Default home directory for an agent: data/agent-home/<agent>."""
    return AGENT_HOME_ROOT / agent


@dataclass(frozen=True)
class Args:
    """Parsed invocation of the wrapper."""

    agent: str
    config: Path
    project_folder: Path
    agent_home: Path
    task: str | None
    login: bool
    project_folder_defaulted: bool
    rig_config: Path
    rig_host: str | None
    network: str | None
    permission_mode: str

    @property
    def effective_task(self) -> str | None:
        """The task to run, or None for an interactive session.

        A login run is always interactive, so it suppresses any task.
        """
        return None if self.login else self.task

    @property
    def is_interactive(self) -> bool:
        return self.effective_task is None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rasp",
        description="Launch an agent session against the raspudger rig.",
    )
    parser.add_argument("--agent", required=True, help="Agent to run (e.g. claude).")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"Optional credentials dotenv file (default: {DEFAULT_CONFIG}).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        dest="data_dir",
        help=f"Base directory for all runtime state (default: {DEFAULT_DATA_DIR}).",
    )
    parser.add_argument(
        "--project-folder",
        type=Path,
        default=None,
        dest="project_folder",
        help="Workspace mounted into the container (default: <data-dir>/projects).",
    )
    parser.add_argument(
        "--agent-home",
        type=Path,
        default=None,
        dest="agent_home",
        help="Persisted agent home: login, settings, skills, plugins "
        "(default: <data-dir>/agent-home/<agent>).",
    )
    parser.add_argument(
        "--task",
        default=None,
        help="Run one objective headless and exit. Omit for an interactive session.",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="Start an interactive session to sign in (browser login), then persist it.",
    )
    parser.add_argument(
        "--rig-config",
        type=Path,
        default=None,
        dest="rig_config",
        help=f"Rig connection settings file: host, SSH key, pins "
        f"(default: {DEFAULT_RIG_CONFIG}). Absent and no --rig-host means no rig.",
    )
    parser.add_argument(
        "--rig-host",
        default=None,
        dest="rig_host",
        help="Pi address, overriding RIG_PI_HOST in the rig config (the volatile bit).",
    )
    parser.add_argument(
        "--network",
        default=None,
        help="Docker network for the container (e.g. the sim's compose network).",
    )
    parser.add_argument(
        "--permission-mode",
        default=DEFAULT_PERMISSION_MODE,
        dest="permission_mode",
        help=f"Agent tool-permission mode (default: {DEFAULT_PERMISSION_MODE}). "
        "Use 'default' to approve tools interactively.",
    )

    return parser


def parse_args(argv: Sequence[str]) -> Args:
    namespace = build_parser().parse_args(list(argv))
    data_dir = namespace.data_dir if namespace.data_dir is not None else DEFAULT_DATA_DIR
    config = namespace.config if namespace.config is not None else DEFAULT_CONFIG
    project_folder_defaulted = namespace.project_folder is None
    project_folder = (
        namespace.project_folder if namespace.project_folder is not None else data_dir / "projects"
    )
    agent_home = (
        namespace.agent_home
        if namespace.agent_home is not None
        else data_dir / "agent-home" / namespace.agent
    )
    rig_config = namespace.rig_config if namespace.rig_config is not None else DEFAULT_RIG_CONFIG

    return Args(
        agent=namespace.agent,
        config=config,
        project_folder=project_folder,
        agent_home=agent_home,
        task=namespace.task,
        login=namespace.login,
        project_folder_defaulted=project_folder_defaulted,
        rig_config=rig_config,
        rig_host=namespace.rig_host,
        network=namespace.network,
        permission_mode=namespace.permission_mode,
    )


def prepare_paths(args: Args) -> None:
    """Ensure the project folder and agent home exist.

    A defaulted project folder is created when missing; an explicitly named one
    must already exist. The agent home is rig-managed and always created. An
    existing path that is not a directory is rejected.
    """
    project = args.project_folder
    if project.exists():
        if not project.is_dir():
            raise UsageError(f"project folder is not a directory: {project}")
    elif args.project_folder_defaulted:
        project.mkdir(parents=True, exist_ok=True)
    else:
        raise UsageError(f"project folder not found: {project}")

    home = args.agent_home
    if home.exists() and not home.is_dir():
        raise UsageError(f"agent home is not a directory: {home}")

    home.mkdir(parents=True, exist_ok=True)

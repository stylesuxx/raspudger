"""Assembly of the `docker run` invocation for an agent session.

This is a pure function: it computes the argument vector and the environment to
inject, without touching Docker. A credential, when present, is passed by name in
the argument vector (``-e NAME``) and by value in the environment map, so the
secret never appears on the command line. The agent home volume persists the
browser login, settings, skills, and plugins, so a credential is optional.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .adapters import AgentAdapter
from .args import Args
from .config import Credential
from .rig import RigLaunch

PROJECT_MOUNT = "/rig/work"
AGENT_HOME_MOUNT = "/agent-home"
RIG_MCP_SERVER_NAME = "rig"


def _mcp_config_json(rig: RigLaunch) -> str:
    """The ``--mcp-config`` payload: one stdio server, env carried as literals."""
    server = {"type": "stdio", "command": "rig-mcp-server", "args": [], "env": rig.env}
    return json.dumps({"mcpServers": {RIG_MCP_SERVER_NAME: server}})


@dataclass(frozen=True)
class DockerInvocation:
    argv: list[str]
    env: dict[str, str]


def build_docker_command(
    *,
    args: Args,
    adapter: AgentAdapter,
    credential: Credential | None,
    image: str,
    rig: RigLaunch | None = None,
    base_url: str | None = None,
    network: str | None = None,
    project_mount: str = PROJECT_MOUNT,
    agent_home_mount: str = AGENT_HOME_MOUNT,
) -> DockerInvocation:
    argv = ["docker", "run", "--rm"]
    effective_network = network if network is not None else args.network
    if effective_network is not None:
        argv += ["--network", effective_network]

    if args.is_interactive and adapter.needs_tty:
        argv.append("-it")

    if adapter.config_dir_env_var is not None:
        argv += ["-v", f"{args.agent_home.resolve()}:{agent_home_mount}"]
        argv += ["-e", f"{adapter.config_dir_env_var}={agent_home_mount}"]

    env: dict[str, str] = {}
    if credential is not None:
        argv += ["-e", credential.env_var]
        env[credential.env_var] = credential.value

    if base_url is not None:
        argv += ["-e", f"ANTHROPIC_BASE_URL={base_url}"]
        # Keep every model request on the proxy path: without this the CLI calls
        # api.anthropic.com directly for version, telemetry, and fast-mode checks.
        argv += ["-e", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1"]

    mcp_config_json: str | None = None
    if rig is not None:
        for mount in rig.mounts:
            spec = f"{mount.host_path.resolve()}:{mount.container_path}"
            if mount.read_only:
                spec += ":ro"

            argv += ["-v", spec]

        mcp_config_json = _mcp_config_json(rig)

    argv += ["-v", f"{args.project_folder.resolve()}:{project_mount}"]
    argv += ["-w", project_mount]
    argv.append(image)
    argv += adapter.launch_command(
        args.effective_task,
        mcp_config_json=mcp_config_json,
        permission_mode=args.permission_mode,
    )

    return DockerInvocation(argv=argv, env=env)

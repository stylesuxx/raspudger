"""Per-agent launch adapters.

An adapter encapsulates what differs between agent CLIs: the binary, the
environment variables it accepts for authentication, and the variable that
relocates its config/credentials directory (so a mounted volume persists a
browser login). Priming is delivered as a CLAUDE.md baked into the image above
the working directory, not via a launch flag, so the session keeps no renderer
restrictions.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import AdapterError


@dataclass(frozen=True)
class AgentAdapter:
    name: str
    binary: str
    auth_env_vars: tuple[str, ...]
    base_url_env_var: str
    config_dir_env_var: str | None
    needs_tty: bool
    mcp_config_flag: str | None = None
    strict_mcp_config_flag: str | None = None
    permission_mode_flag: str | None = None

    def launch_command(
        self,
        task: str | None,
        mcp_config_json: str | None = None,
        permission_mode: str | None = None,
    ) -> list[str]:
        """Build the in-container command that starts the agent CLI.

        With a task, run headless (print mode) and exit. Without one, start an
        interactive session. With an MCP config and an adapter that takes one,
        register that server alone and skip any discovered config, so the rig
        tools are present without an approval prompt. A permission mode, when the
        adapter takes one, sets how tool calls are approved.
        """
        command = [self.binary]
        if mcp_config_json is not None and self.mcp_config_flag is not None:
            if self.strict_mcp_config_flag is not None:
                command.append(self.strict_mcp_config_flag)
            command += [self.mcp_config_flag, mcp_config_json]

        if permission_mode is not None and self.permission_mode_flag is not None:
            command += [self.permission_mode_flag, permission_mode]

        if task is not None:
            command += ["-p", task]

        return command


_ADAPTERS: dict[str, AgentAdapter] = {
    "claude": AgentAdapter(
        name="claude",
        binary="claude",
        # Subscription token preferred; API key is the explicit pay-per-token opt-in.
        auth_env_vars=("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"),
        base_url_env_var="ANTHROPIC_BASE_URL",
        config_dir_env_var="CLAUDE_CONFIG_DIR",
        needs_tty=True,
        mcp_config_flag="--mcp-config",
        strict_mcp_config_flag="--strict-mcp-config",
        permission_mode_flag="--permission-mode",
    ),
}


def resolve_adapter(name: str) -> AgentAdapter:
    """Return the adapter for an agent name, or raise AdapterError."""
    try:
        return _ADAPTERS[name]
    except KeyError:
        known = ", ".join(sorted(_ADAPTERS))
        raise AdapterError(f"unknown agent: {name!r}. Known agents: {known}") from None

import pytest

from raspudger.adapters import AgentAdapter, resolve_adapter
from raspudger.errors import AdapterError


def test_resolve_claude() -> None:
    adapter = resolve_adapter("claude")
    assert isinstance(adapter, AgentAdapter)
    assert adapter.name == "claude"
    assert adapter.binary == "claude"
    assert adapter.auth_env_vars[0] == "CLAUDE_CODE_OAUTH_TOKEN"
    assert "ANTHROPIC_API_KEY" in adapter.auth_env_vars
    assert adapter.base_url_env_var == "ANTHROPIC_BASE_URL"
    assert adapter.config_dir_env_var == "CLAUDE_CONFIG_DIR"
    assert adapter.needs_tty is True


def test_resolve_unknown_raises() -> None:
    with pytest.raises(AdapterError):
        resolve_adapter("nope")


def test_launch_command_interactive_has_no_print_flag() -> None:
    adapter = resolve_adapter("claude")
    assert adapter.launch_command(None) == ["claude"]


def test_launch_command_headless_carries_task() -> None:
    adapter = resolve_adapter("claude")
    assert adapter.launch_command("what is your purpose") == [
        "claude",
        "-p",
        "what is your purpose",
    ]


def test_launch_command_registers_mcp_config_before_task() -> None:
    adapter = resolve_adapter("claude")
    command = adapter.launch_command("scan", mcp_config_json='{"mcpServers":{}}')
    assert command == [
        "claude",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "-p",
        "scan",
    ]


def test_launch_command_without_mcp_config_omits_flags() -> None:
    adapter = resolve_adapter("claude")
    assert adapter.launch_command(None) == ["claude"]
    assert "--mcp-config" not in adapter.launch_command("t")


def test_launch_command_sets_permission_mode() -> None:
    adapter = resolve_adapter("claude")
    command = adapter.launch_command(None, permission_mode="bypassPermissions")
    assert command == ["claude", "--permission-mode", "bypassPermissions"]


def test_launch_command_permission_mode_precedes_task() -> None:
    adapter = resolve_adapter("claude")
    command = adapter.launch_command("scan", permission_mode="bypassPermissions")
    assert command[-2:] == ["-p", "scan"]
    assert "--permission-mode" in command and "bypassPermissions" in command

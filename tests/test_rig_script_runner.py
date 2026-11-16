from __future__ import annotations

import pytest

from rig_mcp.script_runner import (
    ScriptNotFoundError,
    available_scripts,
    build_command,
    canonical_name,
    load_script,
)
from rig_mcp.tools import RigTools
from rig_mcp.transport import ExecResult, FakeTransport


def test_available_scripts_lists_the_probe_catalog() -> None:
    scripts = available_scripts()
    assert "probe_serial" in scripts
    assert scripts == sorted(scripts)


def test_canonical_name_strips_suffix() -> None:
    assert canonical_name("probe_serial.sh") == "probe_serial"
    assert canonical_name("probe_serial") == "probe_serial"


@pytest.mark.parametrize("name", ["", "../etc/passwd", "sub/dir", ".hidden", "a\\b"])
def test_canonical_name_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(ScriptNotFoundError):
        canonical_name(name)


def test_load_script_reads_a_catalog_file() -> None:
    assert "ls -1 /dev/ttyUSB*" in load_script("probe_serial")


def test_load_script_unknown_name_raises() -> None:
    with pytest.raises(ScriptNotFoundError, match="unknown script"):
        load_script("does_not_exist")


def test_build_command_without_args_is_the_body() -> None:
    assert build_command("echo hi\n", []) == "echo hi\n"


def test_build_command_binds_and_quotes_positional_args() -> None:
    command = build_command('echo "$1"\n', ["a b", "x;rm -rf /"])
    assert command == "set -- 'a b' 'x;rm -rf /'\necho \"$1\"\n"


def test_run_script_through_tools_execs_the_loaded_body() -> None:
    body = load_script("probe_serial")
    transport = FakeTransport(exec_results={body: ExecResult("/dev/ttyAMA0\n", "", 0)})
    tools = RigTools(transport=transport)
    result = tools.run_script("probe_serial")
    assert result == {"stdout": "/dev/ttyAMA0\n", "stderr": "", "returncode": 0}
    assert ("exec", body) in transport.ops


def test_run_script_unknown_name_returns_catalog() -> None:
    tools = RigTools(transport=FakeTransport())
    result = tools.run_script("nope")
    assert "unknown script" in str(result["error"])
    assert "probe_serial" in result["scripts"]


def test_list_scripts_through_tools() -> None:
    tools = RigTools(transport=FakeTransport())
    assert "probe_serial" in tools.list_scripts()["scripts"]

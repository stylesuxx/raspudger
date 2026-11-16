import asyncio
import json
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from rig_mcp.capabilities import (
    SERIAL_PROBE_COMMAND,
    CapabilityReporter,
    DeclaredInterface,
)
from rig_mcp.server import build_server
from rig_mcp.state import StateStore
from rig_mcp.tools import RigTools
from rig_mcp.transport import ExecResult, FakeTransport

EXPECTED_TOOLS = {
    "rig_capabilities",
    "pi_exec",
    "list_scripts",
    "run_script",
    "uart_send",
    "uart_expect",
    "uart_exchange",
    "dut_power",
    "dut_power_cycle",
    "state_get",
    "state_record_finding",
}


def _server(tmp_path: Path, transport: FakeTransport | None = None) -> MCPServer:
    resolved = transport or FakeTransport()
    tools = RigTools(transport=resolved)
    reporter = CapabilityReporter(
        transport=resolved,
        declared=[DeclaredInterface("uart", {"tx_pin": 14})],
    )
    return build_server(tools, StateStore(root=tmp_path), reporter)


def _call(app: MCPServer, name: str, arguments: dict[str, object]) -> dict[str, object]:
    result = asyncio.run(app.call_tool(name, arguments))
    assert result.is_error is False
    payload: dict[str, object] = json.loads(result.content[0].text)
    return payload


def test_lists_expected_tools(tmp_path: Path) -> None:
    app = _server(tmp_path)
    names = {t.name for t in asyncio.run(app.list_tools())}
    assert names >= EXPECTED_TOOLS


def test_pi_exec_through_server(tmp_path: Path) -> None:
    transport = FakeTransport(exec_results={"ls": ExecResult("a", "", 0)})
    app = _server(tmp_path, transport)
    assert _call(app, "pi_exec", {"command": "ls"}) == {
        "stdout": "a",
        "stderr": "",
        "returncode": 0,
    }


def test_run_script_through_server(tmp_path: Path) -> None:
    from rig_mcp.script_runner import load_script

    body = load_script("probe_serial")
    transport = FakeTransport(exec_results={body: ExecResult("/dev/ttyAMA0\n", "", 0)})
    app = _server(tmp_path, transport)
    assert _call(app, "run_script", {"name": "probe_serial"}) == {
        "stdout": "/dev/ttyAMA0\n",
        "stderr": "",
        "returncode": 0,
    }


def test_list_scripts_through_server(tmp_path: Path) -> None:
    app = _server(tmp_path)
    payload = _call(app, "list_scripts", {})
    scripts = payload["scripts"]
    assert isinstance(scripts, list)
    assert "probe_serial" in scripts


def test_rig_capabilities_through_server(tmp_path: Path) -> None:
    transport = FakeTransport(
        exec_results={SERIAL_PROBE_COMMAND: ExecResult("/dev/ttyAMA0\n", "", 0)}
    )
    app = _server(tmp_path, transport)
    payload = _call(app, "rig_capabilities", {})
    declared = payload["declared"]
    assert isinstance(declared, list)
    assert declared[0]["name"] == "uart"
    detected = payload["detected"]
    assert isinstance(detected, dict)
    assert detected["serial_devices"] == ["/dev/ttyAMA0"]
    assert payload["discrepancies"] == []


def test_state_roundtrip_through_server(tmp_path: Path) -> None:
    app = _server(tmp_path)
    _call(app, "state_record_finding", {"device": "d1", "finding": {"cve": "CVE-9"}})
    payload = _call(app, "state_get", {"device": "d1"})
    findings = payload["findings"]
    assert isinstance(findings, list)
    assert findings[0]["cve"] == "CVE-9"

import asyncio
import json
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from rig_mcp.server import build_server
from rig_mcp.state import StateStore
from rig_mcp.tools import RigTools
from rig_mcp.transport import ExecResult, FakeTransport

EXPECTED_TOOLS = {
    "pi_exec",
    "uart_send",
    "uart_expect",
    "uart_exchange",
    "dut_power",
    "dut_power_cycle",
    "state_get",
    "state_record_finding",
}


def _server(tmp_path: Path, transport: FakeTransport | None = None) -> MCPServer:
    tools = RigTools(transport=transport or FakeTransport())
    return build_server(tools, StateStore(root=tmp_path))


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


def test_state_roundtrip_through_server(tmp_path: Path) -> None:
    app = _server(tmp_path)
    _call(app, "state_record_finding", {"device": "d1", "finding": {"cve": "CVE-9"}})
    payload = _call(app, "state_get", {"device": "d1"})
    findings = payload["findings"]
    assert isinstance(findings, list)
    assert findings[0]["cve"] == "CVE-9"

import asyncio
import json
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from rig_mcp.capabilities import (
    SERIAL_PROBE_COMMAND,
    CapabilityReporter,
    DeclaredInterface,
)
from rig_mcp.config import DutNetwork
from rig_mcp.server import build_server
from rig_mcp.state import StateStore
from rig_mcp.tools import RigTools
from rig_mcp.transport import ExecResult, FakeTransport

EXPECTED_TOOLS = {
    "rig_capabilities",
    "dut_network_info",
    "pi_exec",
    "list_scripts",
    "run_script",
    "uart_send",
    "uart_expect",
    "uart_exchange",
    "uart_capture",
    "uart_configure",
    "uart_handoff",
    "dut_power",
    "dut_power_cycle",
    "state_get",
    "state_record_finding",
    "device_open",
    "state_snapshot",
    "state_restore",
    "state_list_snapshots",
}


def _server(
    tmp_path: Path,
    transport: FakeTransport | None = None,
    dut_network: DutNetwork | None = None,
    device: str | None = "router-a",
    has_power: bool = True,
) -> MCPServer:
    resolved = transport or FakeTransport()
    tools = RigTools(transport=resolved)
    reporter = CapabilityReporter(
        transport=resolved,
        declared=[DeclaredInterface("uart", {"tx_pin": 14})],
    )
    return build_server(tools, StateStore(root=tmp_path), reporter, dut_network, device, has_power)


def _call(app: MCPServer, name: str, arguments: dict[str, object]) -> dict[str, object]:
    result = asyncio.run(app.call_tool(name, arguments))
    assert result.is_error is False
    payload: dict[str, object] = json.loads(result.content[0].text)
    return payload


def test_lists_expected_tools(tmp_path: Path) -> None:
    app = _server(tmp_path)
    names = {t.name for t in asyncio.run(app.list_tools())}
    assert names >= EXPECTED_TOOLS


def test_power_tools_absent_without_power(tmp_path: Path) -> None:
    app = _server(tmp_path, has_power=False)
    names = {t.name for t in asyncio.run(app.list_tools())}
    assert "dut_power" not in names
    assert "dut_power_cycle" not in names
    # The rest of the surface is unaffected.
    assert "uart_send" in names
    assert "pi_exec" in names


def test_pi_exec_through_server(tmp_path: Path) -> None:
    transport = FakeTransport(exec_results={"ls": ExecResult("a", "", 0)})
    app = _server(tmp_path, transport)
    assert _call(app, "pi_exec", {"command": "ls"}) == {
        "stdout": "a",
        "stderr": "",
        "returncode": 0,
        "truncated": False,
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
        "truncated": False,
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


def test_dut_network_info_unconfigured(tmp_path: Path) -> None:
    app = _server(tmp_path)
    assert _call(app, "dut_network_info", {}) == {"configured": False}


def test_dut_network_info_configured(tmp_path: Path) -> None:
    network = DutNetwork(ssid="raspudger-test", psk="sekret", subnet="192.168.10.0/24", iface=None)
    app = _server(tmp_path, dut_network=network)
    assert _call(app, "dut_network_info", {}) == {
        "configured": True,
        "ssid": "raspudger-test",
        "psk": "sekret",
        "subnet": "192.168.10.0/24",
        "iface": None,
    }


def test_device_open_through_server(tmp_path: Path) -> None:
    app = _server(tmp_path)
    payload = _call(app, "device_open", {"identity": {"soc": "bcm2711"}})
    assert payload["warnings"] == []
    record = payload["record"]
    assert isinstance(record, dict)
    assert record["slug"] == "router-a"


def test_snapshot_and_restore_through_server(tmp_path: Path) -> None:
    app = _server(tmp_path)
    _call(app, "state_record_finding", {"finding": {"cve": "CVE-1"}})
    _call(app, "state_snapshot", {"snapshot_id": "s1"})
    _call(app, "state_record_finding", {"finding": {"cve": "CVE-2"}})
    _call(app, "state_restore", {"snapshot_id": "s1"})
    findings = _call(app, "state_get", {})["findings"]
    assert isinstance(findings, list)
    assert [f["cve"] for f in findings] == ["CVE-1"]


def test_restore_missing_snapshot_returns_error(tmp_path: Path) -> None:
    app = _server(tmp_path)
    payload = _call(app, "state_restore", {"snapshot_id": "nope"})
    assert "no snapshot" in str(payload["error"])


def test_state_roundtrip_through_server(tmp_path: Path) -> None:
    app = _server(tmp_path)
    _call(app, "state_record_finding", {"finding": {"cve": "CVE-9"}})
    payload = _call(app, "state_get", {})
    findings = payload["findings"]
    assert isinstance(findings, list)
    assert findings[0]["cve"] == "CVE-9"


def test_state_tools_error_without_bound_device(tmp_path: Path) -> None:
    app = _server(tmp_path, device=None)
    payload = _call(app, "state_record_finding", {"finding": {"cve": "CVE-1"}})
    assert "no device is bound" in str(payload["error"])


def test_uart_capture_through_server_writes_workspace_file(tmp_path: Path) -> None:
    transport = FakeTransport(uart_chunks=[b"boot ", b"READY\n"])
    app = _server(tmp_path, transport)
    payload = _call(app, "uart_capture", {"out_name": "boot.txt", "until_pattern": "READY"})
    assert payload["ended_on"] == "pattern"
    captured = tmp_path / "router-a" / "captures" / "boot.txt"
    assert captured.read_bytes() == b"boot READY\n"


def test_uart_capture_requires_bound_device(tmp_path: Path) -> None:
    app = _server(tmp_path, device=None)
    payload = _call(app, "uart_capture", {"out_name": "boot.txt"})
    assert "no device is bound" in str(payload["error"])

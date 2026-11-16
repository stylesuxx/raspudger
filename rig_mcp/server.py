"""The rig MCP server: exposes the rig tools over MCP.

Transport-agnostic: ``build_server`` takes ``RigTools`` (over any ``Transport``)
and a ``StateStore``, so the fast tests drive it over ``FakeTransport`` and the
live server over ``SshTransport``.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .capabilities import CapabilityReporter
from .config import DutNetwork
from .state import StateStore
from .tools import RigTools


def build_server(
    tools: RigTools,
    store: StateStore,
    reporter: CapabilityReporter,
    dut_network: DutNetwork | None = None,
    name: str = "raspudger-rig",
) -> MCPServer:
    app = MCPServer(name)

    @app.tool()
    def rig_capabilities() -> dict[str, object]:
        return reporter.report()

    @app.tool()
    def dut_network_info() -> dict[str, object]:
        """Credentials for the isolated test network a WiFi DUT joins.

        To put a DUT on the rig's network, join it to this SSID with this PSK;
        once connected the DUT appears on the Pi's subnet and is reachable from
        the Pi for scanning. Returns ``configured`` False when no test network is
        set for this bench.
        """
        if dut_network is None:
            return {"configured": False}

        return {
            "configured": True,
            "ssid": dut_network.ssid,
            "psk": dut_network.psk,
            "subnet": dut_network.subnet,
            "iface": dut_network.iface,
        }

    @app.tool()
    def pi_exec(command: str, timeout_s: float = 30.0) -> dict[str, object]:
        return tools.pi_exec(command, timeout_s)

    @app.tool()
    def list_scripts() -> dict[str, object]:
        return tools.list_scripts()

    @app.tool()
    def run_script(
        name: str, args: list[str] | None = None, timeout_s: float = 30.0
    ) -> dict[str, object]:
        return tools.run_script(name, args, timeout_s)

    @app.tool()
    def uart_send(data: str) -> dict[str, object]:
        return tools.uart_send(data)

    @app.tool()
    def uart_expect(pattern: str, timeout_s: float) -> dict[str, object]:
        return tools.uart_expect(pattern, timeout_s)

    @app.tool()
    def uart_exchange(
        steps: list[dict[str, object]], default_timeout_s: float = 1.0
    ) -> dict[str, object]:
        return tools.uart_exchange(steps, default_timeout_s)

    @app.tool()
    def dut_power(state: str) -> dict[str, object]:
        return tools.dut_power(state)

    @app.tool()
    def dut_power_cycle(off_ms: int = 2000) -> dict[str, object]:
        return tools.dut_power_cycle(off_ms)

    @app.tool()
    def state_get(device: str) -> dict[str, object]:
        return store.get(device)

    @app.tool()
    def state_record_finding(device: str, finding: dict[str, object]) -> dict[str, object]:
        return store.record_finding(device, finding)

    return app

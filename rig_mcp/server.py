"""The rig MCP server: exposes the rig tools over MCP.

Transport-agnostic: ``build_server`` takes ``RigTools`` (over any ``Transport``)
and a ``StateStore``, so the fast tests drive it over ``FakeTransport`` and the
live server over ``SshTransport``.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .capabilities import CapabilityReporter
from .config import DutNetwork
from .state import StateError, StateStore
from .tools import RigTools

_NO_DEVICE_ERROR = "no device is bound to this session; launch the rig with --device <slug>"


def build_server(
    tools: RigTools,
    store: StateStore,
    reporter: CapabilityReporter,
    dut_network: DutNetwork | None = None,
    device: str | None = None,
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
    def state_get() -> dict[str, object]:
        """Return the bound device's cumulative project state (its findings)."""
        if device is None:
            return {"error": _NO_DEVICE_ERROR}

        return store.get(device)

    @app.tool()
    def state_record_finding(finding: dict[str, object]) -> dict[str, object]:
        """Append a finding to the bound device's persistent state."""
        if device is None:
            return {"error": _NO_DEVICE_ERROR}

        return store.record_finding(device, finding)

    @app.tool()
    def device_open(identity: dict[str, object]) -> dict[str, object]:
        """Load or create the bound device's record from observed traits.

        Pass the identity traits you read off the DUT (a UART banner, an ``id``
        command, a chip marking). A later session whose traits differ returns a
        warning that a different DUT may be wired under this device slug.
        """
        if device is None:
            return {"error": _NO_DEVICE_ERROR}

        return store.open_device(device, identity)

    @app.tool()
    def state_snapshot(snapshot_id: str) -> dict[str, object]:
        """Copy the bound device's state into a named, restorable snapshot."""
        if device is None:
            return {"error": _NO_DEVICE_ERROR}

        return store.snapshot(device, snapshot_id)

    @app.tool()
    def state_restore(snapshot_id: str) -> dict[str, object]:
        """Roll the bound device's state back to a named snapshot."""
        if device is None:
            return {"error": _NO_DEVICE_ERROR}

        try:
            return store.restore(device, snapshot_id)
        except StateError as error:
            return {"error": str(error)}

    @app.tool()
    def state_list_snapshots() -> dict[str, object]:
        """List the bound device's snapshot ids."""
        if device is None:
            return {"error": _NO_DEVICE_ERROR}

        return {"snapshots": store.list_snapshots(device)}

    return app

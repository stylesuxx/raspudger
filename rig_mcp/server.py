"""The rig MCP server: exposes the rig tools over MCP.

Transport-agnostic: ``build_server`` takes ``RigTools`` (over any ``Transport``)
and a ``StateStore``, so the fast tests drive it over ``FakeTransport`` and the
live server over ``SshTransport``.

Most tools are pure pass-throughs to a method on ``RigTools`` or ``DeviceState``,
so they are registered by reference from those methods: the agent-facing name,
description, and parameter schema come from the implementation and cannot drift
from it. Only a tool with server-local logic (a capability report, the network
credentials, a capture that spans the transport and the device workspace) is
written out here.
"""

from __future__ import annotations

from collections.abc import Callable

from mcp.server.mcpserver import MCPServer

from .capabilities import CapabilityReporter
from .config import DutNetwork
from .state import DeviceState, StateError, StateStore
from .tools import RigTools


def build_server(
    tools: RigTools,
    store: StateStore,
    reporter: CapabilityReporter,
    dut_network: DutNetwork | None = None,
    device: str | None = None,
    name: str = "raspudger-rig",
) -> MCPServer:
    app = MCPServer(name)
    session = DeviceState(store, device)

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
    def uart_capture(
        out_name: str,
        trigger: str = "",
        until_pattern: str | None = None,
        timeout_s: float = 30.0,
        idle_timeout_s: float | None = None,
    ) -> dict[str, object]:
        """Stream UART output to a file in the device workspace.

        Use this for bulk reads (boot logs, memory or flash dumps) instead of
        reading through the interactive tools: the capture lands on disk and only
        a short ``head`` plus the file path come back, so large output never
        floods the agent's context or trips the output cap.
        """
        try:
            path = session.capture_path(out_name)
        except StateError as error:
            return {"error": str(error)}

        return tools.uart_capture(path, trigger, until_pattern, timeout_s, idle_timeout_s)

    # Pass-through tools: (implementation method, agent-facing tool name). The
    # method is the single source of signature and description; adding a tool is
    # one line here plus the method on RigTools or DeviceState.
    passthrough: tuple[tuple[Callable[..., dict[str, object]], str], ...] = (
        (tools.pi_exec, "pi_exec"),
        (tools.list_scripts, "list_scripts"),
        (tools.run_script, "run_script"),
        (tools.uart_send, "uart_send"),
        (tools.uart_expect, "uart_expect"),
        (tools.uart_exchange, "uart_exchange"),
        (tools.uart_configure, "uart_configure"),
        (tools.uart_handoff, "uart_handoff"),
        (tools.dut_power, "dut_power"),
        (tools.dut_power_cycle, "dut_power_cycle"),
        (session.open_device, "device_open"),
        (session.get, "state_get"),
        (session.record_finding, "state_record_finding"),
        (session.snapshot, "state_snapshot"),
        (session.restore, "state_restore"),
        (session.list_snapshots, "state_list_snapshots"),
    )
    for method, tool_name in passthrough:
        app.add_tool(method, name=tool_name)

    return app

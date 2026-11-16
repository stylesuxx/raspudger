"""Entry point for the live rig MCP server, spoken over stdio.

Claude Code launches this as an MCP server (``command`` in ``.mcp.json``): it
reads ``RigConfig`` from the environment, opens SSH to the Pi and a TCP socket to
ser2net for the UART, and serves the rig tools on stdin/stdout. The wiring here
is the only code that touches the real environment and network; everything it
assembles is unit-tested over fakes.
"""

from __future__ import annotations

import os

from .capabilities import CapabilityReporter
from .config import RigConfig
from .server import build_server
from .ssh_transport import SshTransport, connect_uart, make_ssh_runner
from .state import StateStore
from .tools import RigTools


def build_live_tools(config: RigConfig) -> tuple[RigTools, StateStore, CapabilityReporter]:
    runner = make_ssh_runner(
        host=config.pi_host,
        user=config.pi_user,
        key=config.pi_ssh_key,
        port=config.pi_ssh_port,
        known_hosts=config.pi_known_hosts,
    )
    transport = SshTransport(
        runner,
        lambda: connect_uart(config.uart_host, config.uart_port),
        config.pins,
    )
    tools = RigTools(transport, read_timeout=config.uart_read_timeout)
    store = StateStore(config.state_root)
    reporter = CapabilityReporter.from_config(config, transport)

    return tools, store, reporter


def main() -> None:
    config = RigConfig.from_env(os.environ)
    tools, store, reporter = build_live_tools(config)
    build_server(tools, store, reporter).run("stdio")


if __name__ == "__main__":
    main()

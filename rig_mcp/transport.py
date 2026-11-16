"""The transport seam between the rig tools and the Pi.

The ``Transport`` protocol is a small set of primitives. ``FakeTransport`` models
them in memory for tests; the real ``SshTransport`` implements them over SSH
(`exec`, `pinctrl`) and a ser2net TCP socket (UART).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ExecResult:
    stdout: str
    stderr: str
    returncode: int


class Transport(Protocol):
    def exec(self, command: str, timeout_s: float) -> ExecResult: ...
    def uart_write(self, data: bytes) -> None: ...
    def uart_read(self, timeout_s: float) -> bytes: ...
    def set_power(self, on: bool) -> None: ...
    def set_uart_tristate(self, tristate: bool) -> None: ...


@dataclass
class FakeTransport:
    """In-memory transport that records an ordered op-log for assertions."""

    exec_results: dict[str, ExecResult] = field(default_factory=dict)
    uart_chunks: list[bytes] = field(default_factory=list)
    ops: list[tuple[object, ...]] = field(default_factory=list)

    def exec(self, command: str, timeout_s: float) -> ExecResult:
        self.ops.append(("exec", command))
        return self.exec_results.get(command, ExecResult("", "", 0))

    def uart_write(self, data: bytes) -> None:
        self.ops.append(("uart_write", data))

    def uart_read(self, timeout_s: float) -> bytes:
        self.ops.append(("uart_read",))
        if self.uart_chunks:
            return self.uart_chunks.pop(0)

        return b""

    def set_power(self, on: bool) -> None:
        self.ops.append(("power", on))

    def set_uart_tristate(self, tristate: bool) -> None:
        self.ops.append(("uart_tristate", tristate))

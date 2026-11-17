"""The real transport: SSH for exec and GPIO (`pinctrl`), a TCP socket for UART.

This implements the same ``Transport`` protocol as ``FakeTransport``. The command
construction (which `pinctrl` calls drive power and UART tristate) is unit-tested
by injecting a fake runner and socket; the actual SSH/socket I/O is exercised
against the container sim and real hardware, not in the unit gate.

GPIO via `pinctrl`:
- power relay: ``pinctrl set <pin> op dh|dl`` (drive high/low; polarity in PinMap).
- UART TX tristate: ``pinctrl set <tx> ip`` (input = high-Z) to tristate,
  ``pinctrl set <tx> a0`` (alt0 = UART) to restore.
"""

from __future__ import annotations

import contextlib
import socket
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .transport import ExecResult

SshRunner = Callable[[str, float], ExecResult]
GPIO_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class PinMap:
    uart_tx: int
    power: int | None = None
    power_active_high: bool = True


class SocketLike(Protocol):
    def sendall(self, data: bytes) -> None: ...
    def recv(self, bufsize: int) -> bytes: ...
    def settimeout(self, timeout: float | None) -> None: ...


UartConnector = Callable[[], SocketLike]


class SshTransport:
    def __init__(self, runner: SshRunner, uart_connector: UartConnector, pins: PinMap) -> None:
        self._run = runner
        self._connect_uart = uart_connector
        self._uart: SocketLike | None = None
        self._pins = pins

    def exec(self, command: str, timeout_s: float) -> ExecResult:
        return self._run(command, timeout_s)

    def _uart_socket(self) -> SocketLike:
        # Connect on first UART use, so the server starts even when the UART
        # bridge is unreachable and a UART fault never blocks exec or GPIO.
        if self._uart is None:
            self._uart = self._connect_uart()

        return self._uart

    def _reset_uart(self) -> None:
        # Drop the cached socket so the next use reconnects. A ser2net restart or
        # a dropped TCP leaves the old socket dead, and reusing it never heals.
        sock = self._uart
        self._uart = None
        if sock is None:
            return

        closer = getattr(sock, "close", None)
        if callable(closer):
            with contextlib.suppress(OSError):
                closer()

    def uart_reset(self) -> None:
        # Public reset: callers that restart ser2net (a lease or a reconfigure)
        # drop the stale socket so the next UART use reconnects deterministically.
        self._reset_uart()

    def uart_write(self, data: bytes) -> None:
        for attempt in (0, 1):
            try:
                self._uart_socket().sendall(data)
                return
            except OSError:
                self._reset_uart()
                if attempt == 1:
                    raise

    def uart_read(self, timeout_s: float) -> bytes:
        for attempt in (0, 1):
            try:
                sock = self._uart_socket()
                sock.settimeout(timeout_s)
                chunk = sock.recv(4096)

            except TimeoutError:
                return b""

            except OSError:
                self._reset_uart()
                if attempt == 1:
                    raise

                continue

            # An empty recv is an orderly EOF: the bridge closed the connection.
            # Reconnect once; a genuinely idle line raises TimeoutError instead.
            if chunk == b"" and attempt == 0:
                self._reset_uart()
                continue

            return chunk

        return b""

    def set_power(self, on: bool) -> None:
        # Guard a hardware actuation: the power tools are unregistered when no
        # power pin is configured, so reaching here without one is a wiring bug.
        if self._pins.power is None:
            raise RuntimeError("power control requested but no power pin is configured")

        level = "dh" if on == self._pins.power_active_high else "dl"
        self._run(f"pinctrl set {self._pins.power} op {level}", GPIO_TIMEOUT_S)

    def set_uart_tristate(self, tristate: bool) -> None:
        mode = "ip" if tristate else "a0"
        self._run(f"pinctrl set {self._pins.uart_tx} {mode}", GPIO_TIMEOUT_S)


def make_ssh_runner(
    host: str,
    user: str,
    key: Path | None = None,
    port: int = 22,
    known_hosts: Path | None = None,
    options: list[str] | None = None,
) -> SshRunner:
    """Build an SshRunner that shells the system ``ssh`` client.

    ``known_hosts`` points host-key verification at a dedicated file instead of
    the user's ``~/.ssh/known_hosts``: the rig's Pi is disposable, so its host
    key changes on every reflash, and its keys stay out of the user's file.
    Clear this file to re-trust a reflashed Pi.
    """
    base = [
        "ssh",
        "-p",
        str(port),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "LogLevel=ERROR",
    ]

    if known_hosts is not None:
        base += ["-o", f"UserKnownHostsFile={known_hosts}"]

    if key is not None:
        # IdentitiesOnly: present only this key, never the user's ~/.ssh/id_*.
        base += ["-i", str(key), "-o", "IdentitiesOnly=yes"]

    for option in options or []:
        base += ["-o", option]

    target = f"{user}@{host}"

    def run(command: str, timeout_s: float) -> ExecResult:
        try:
            completed = subprocess.run(
                [*base, target, "--", command],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ExecResult("", f"ssh timeout after {timeout_s}s", 124)

        return ExecResult(completed.stdout, completed.stderr, completed.returncode)

    return run


def connect_uart(host: str, port: int, timeout: float = 5.0) -> socket.socket:
    """Open a TCP connection to the Pi's ser2net bridge for the UART."""
    return socket.create_connection((host, port), timeout=timeout)

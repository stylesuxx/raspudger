from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from rig_mcp.ssh_transport import PinMap, SocketLike, SshTransport, UartConnector, make_ssh_runner
from rig_mcp.transport import ExecResult


class FakeRunner:
    def __init__(self, results: dict[str, ExecResult] | None = None) -> None:
        self.calls: list[tuple[str, float]] = []
        self.results = results or {}

    def __call__(self, command: str, timeout_s: float) -> ExecResult:
        self.calls.append((command, timeout_s))
        return self.results.get(command, ExecResult("", "", 0))


class FakeSocket:
    def __init__(
        self,
        chunks: Sequence[bytes] = (),
        raise_timeout: bool = False,
        fail_send_times: int = 0,
        fail_recv_times: int = 0,
    ) -> None:
        self.sent: list[bytes] = []
        self.chunks = list(chunks)
        self.timeout: float | None = None
        self.raise_timeout = raise_timeout
        self.fail_send_times = fail_send_times
        self.fail_recv_times = fail_recv_times
        self.closed = False

    def sendall(self, data: bytes) -> None:
        if self.fail_send_times > 0:
            self.fail_send_times -= 1
            raise BrokenPipeError("uart bridge dropped")
        self.sent.append(data)

    def recv(self, bufsize: int) -> bytes:
        if self.fail_recv_times > 0:
            self.fail_recv_times -= 1
            raise ConnectionResetError("uart bridge dropped")
        if self.raise_timeout:
            raise TimeoutError
        # An empty list models an orderly EOF (the bridge closed the socket).
        return self.chunks.pop(0) if self.chunks else b""

    def settimeout(self, timeout: float | None) -> None:
        self.timeout = timeout

    def close(self) -> None:
        self.closed = True


PINS = PinMap(power=17, uart_tx=14)


def test_exec_passthrough() -> None:
    runner = FakeRunner({"ls": ExecResult("a", "", 0)})
    transport = SshTransport(runner, lambda: FakeSocket(), PINS)
    assert transport.exec("ls", 5.0) == ExecResult("a", "", 0)
    assert runner.calls == [("ls", 5.0)]


def test_set_power_active_high() -> None:
    runner = FakeRunner()
    transport = SshTransport(runner, lambda: FakeSocket(), PINS)
    transport.set_power(True)
    transport.set_power(False)
    assert runner.calls[0][0] == "pinctrl set 17 op dh"
    assert runner.calls[1][0] == "pinctrl set 17 op dl"


def test_set_power_active_low() -> None:
    runner = FakeRunner()
    pins = PinMap(power=17, uart_tx=14, power_active_high=False)
    transport = SshTransport(runner, lambda: FakeSocket(), pins)
    transport.set_power(True)
    assert runner.calls[0][0] == "pinctrl set 17 op dl"


def test_set_uart_tristate() -> None:
    runner = FakeRunner()
    transport = SshTransport(runner, lambda: FakeSocket(), PINS)
    transport.set_uart_tristate(True)
    transport.set_uart_tristate(False)
    assert runner.calls[0][0] == "pinctrl set 14 ip"
    assert runner.calls[1][0] == "pinctrl set 14 a0"


def test_uart_write() -> None:
    sock = FakeSocket()
    transport = SshTransport(FakeRunner(), lambda: sock, PINS)
    transport.uart_write(b"hello")
    assert sock.sent == [b"hello"]


def test_uart_read_returns_chunk() -> None:
    sock = FakeSocket(chunks=[b"data"])
    transport = SshTransport(FakeRunner(), lambda: sock, PINS)
    assert transport.uart_read(0.5) == b"data"
    assert sock.timeout == 0.5


def test_uart_read_timeout_returns_empty() -> None:
    sock = FakeSocket(raise_timeout=True)
    transport = SshTransport(FakeRunner(), lambda: sock, PINS)
    assert transport.uart_read(0.1) == b""


def test_uart_is_connected_lazily_and_cached() -> None:
    sock = FakeSocket(chunks=[b"a", b"b"])
    connects = 0

    def connector() -> FakeSocket:
        nonlocal connects
        connects += 1
        return sock

    transport = SshTransport(FakeRunner(), connector, PINS)
    # exec and GPIO never touch the UART, so the connector is not called.
    transport.exec("ls", 1.0)
    transport.set_power(True)
    assert connects == 0
    # First UART use connects; later uses reuse the one socket.
    transport.uart_write(b"x")
    transport.uart_read(0.1)
    assert connects == 1


def test_exec_works_when_uart_connector_fails() -> None:
    def failing_connector() -> FakeSocket:
        raise ConnectionRefusedError("uart bridge down")

    transport = SshTransport(FakeRunner({"ls": ExecResult("ok", "", 0)}), failing_connector, PINS)
    assert transport.exec("ls", 1.0).stdout == "ok"
    transport.set_power(False)


def _socket_sequence(sockets: list[FakeSocket]) -> tuple[UartConnector, Callable[[], int]]:
    served = iter(sockets)
    count = 0

    def connector() -> SocketLike:
        nonlocal count
        count += 1
        return next(served)

    return connector, lambda: count


def test_uart_write_reconnects_after_drop() -> None:
    dead = FakeSocket(fail_send_times=1)
    fresh = FakeSocket()
    connector, connects = _socket_sequence([dead, fresh])
    transport = SshTransport(FakeRunner(), connector, PINS)
    transport.uart_write(b"hello")
    assert connects() == 2
    assert dead.closed is True
    assert fresh.sent == [b"hello"]


def test_uart_read_reconnects_on_eof() -> None:
    dead = FakeSocket(chunks=[])
    fresh = FakeSocket(chunks=[b"after"])
    connector, connects = _socket_sequence([dead, fresh])
    transport = SshTransport(FakeRunner(), connector, PINS)
    assert transport.uart_read(0.1) == b"after"
    assert dead.closed is True
    assert connects() == 2


def test_uart_read_reconnects_after_error() -> None:
    dead = FakeSocket(fail_recv_times=1)
    fresh = FakeSocket(chunks=[b"ok"])
    connector, connects = _socket_sequence([dead, fresh])
    transport = SshTransport(FakeRunner(), connector, PINS)
    assert transport.uart_read(0.1) == b"ok"
    assert dead.closed is True


def test_uart_write_raises_when_bridge_stays_down() -> None:
    def failing_connector() -> SocketLike:
        raise ConnectionRefusedError("uart bridge down")

    transport = SshTransport(FakeRunner(), failing_connector, PINS)
    with pytest.raises(OSError):
        transport.uart_write(b"x")


def _capture_ssh_argv(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "out", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_make_ssh_runner_builds_target_and_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_ssh_argv(monkeypatch)
    runner = make_ssh_runner(host="pi.local", user="rig", port=2222)
    result = runner("uname -m", 30.0)
    assert result.stdout == "out"
    argv = calls[0]
    assert argv[0] == "ssh"
    assert "rig@pi.local" in argv
    assert argv[-2:] == ["--", "uname -m"]
    assert "-p" in argv and "2222" in argv
    assert "BatchMode=yes" in argv
    assert "StrictHostKeyChecking=accept-new" in argv
    assert "LogLevel=ERROR" in argv


def test_make_ssh_runner_isolates_identity_and_known_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_ssh_argv(monkeypatch)
    runner = make_ssh_runner(
        host="pi.local",
        user="rig",
        key=Path("/keys/rig"),
        known_hosts=Path("/state/pi-known_hosts"),
    )
    runner("true", 5.0)
    argv = calls[0]
    assert "IdentitiesOnly=yes" in argv
    assert "-i" in argv and "/keys/rig" in argv
    assert "UserKnownHostsFile=/state/pi-known_hosts" in argv


def test_make_ssh_runner_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 0.0))

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = make_ssh_runner(host="pi.local", user="rig")
    result = runner("sleep 99", 1.0)
    assert result.returncode == 124
    assert "timeout" in result.stderr

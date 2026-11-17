from collections.abc import Iterator
from pathlib import Path
from unittest.mock import Mock

from rig_mcp.tools import CAPTURE_HEAD_BYTES, MAX_OUTPUT_CHARS, RigTools
from rig_mcp.transport import ExecResult, FakeTransport


class FakeClock:
    """A monotonic clock that advances a fixed step per call, for bounded loops."""

    def __init__(self, step: float = 1.0) -> None:
        self._now = 0.0
        self._step = step

    def __call__(self) -> float:
        now = self._now
        self._now += self._step
        return now


def test_pi_exec_shapes_result() -> None:
    transport = FakeTransport(exec_results={"ls": ExecResult("a\nb", "", 0)})
    tools = RigTools(transport=transport)
    assert tools.pi_exec("ls") == {
        "stdout": "a\nb",
        "stderr": "",
        "returncode": 0,
        "truncated": False,
    }


def test_pi_exec_caps_long_stdout_and_marks_it() -> None:
    flood = "x" * (MAX_OUTPUT_CHARS + 500)
    transport = FakeTransport(exec_results={"dmesg": ExecResult(flood, "", 0)})
    tools = RigTools(transport=transport)
    result = tools.pi_exec("dmesg")
    assert result["truncated"] is True
    stdout = result["stdout"]
    assert isinstance(stdout, str)
    assert stdout.startswith("x" * MAX_OUTPUT_CHARS)
    assert f"first {MAX_OUTPUT_CHARS} of {len(flood)} characters" in stdout


def test_pi_exec_caps_long_stderr() -> None:
    transport = FakeTransport(
        exec_results={"noisy": ExecResult("", "e" * (MAX_OUTPUT_CHARS + 1), 1)}
    )
    tools = RigTools(transport=transport)
    result = tools.pi_exec("noisy")
    assert result["truncated"] is True
    assert "truncated" in str(result["stderr"])


def test_pi_exec_at_the_cap_is_not_truncated() -> None:
    exact = "y" * MAX_OUTPUT_CHARS
    transport = FakeTransport(exec_results={"ls": ExecResult(exact, "", 0)})
    tools = RigTools(transport=transport)
    result = tools.pi_exec("ls")
    assert result["truncated"] is False
    assert result["stdout"] == exact


def test_uart_send_counts_bytes() -> None:
    transport = FakeTransport()
    tools = RigTools(transport=transport)
    assert tools.uart_send("hello") == {"bytes_written": 5}
    assert ("uart_write", b"hello") in transport.ops


def test_uart_expect_matches() -> None:
    transport = FakeTransport(uart_chunks=[b"boot", b"login: "])
    tools = RigTools(transport=transport)
    out = tools.uart_expect("login: ", timeout_s=5.0)
    assert out["matched"] is True
    assert out["matched_text"] == "login: "


def test_uart_expect_times_out() -> None:
    ticks: Iterator[float] = iter([0.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    transport = FakeTransport(uart_chunks=[b"noise"])
    tools = RigTools(transport=transport, clock=lambda: next(ticks))
    out = tools.uart_expect("WONTMATCH", timeout_s=5.0)
    assert out["matched"] is False
    assert out["matched_text"] is None


def test_power_cycle_interlock_order_and_sleep() -> None:
    transport = FakeTransport()
    sleep = Mock()
    tools = RigTools(transport=transport, sleep=sleep)
    tools.dut_power_cycle(off_ms=2000)
    assert transport.ops == [
        ("uart_tristate", True),
        ("power", False),
        ("power", True),
        ("uart_tristate", False),
    ]
    sleep.assert_called_once_with(2.0)


def test_dut_power() -> None:
    transport = FakeTransport()
    tools = RigTools(transport=transport)
    assert tools.dut_power("off") == {"state": "off"}
    assert ("power", False) in transport.ops


class UnreachableUart:
    def exec(self, command: str, timeout_s: float) -> ExecResult:
        return ExecResult("", "", 0)

    def uart_write(self, data: bytes) -> None:
        raise ConnectionRefusedError("uart bridge down")

    def uart_read(self, timeout_s: float) -> bytes:
        raise ConnectionRefusedError("uart bridge down")

    def set_power(self, on: bool) -> None:
        return None

    def set_uart_tristate(self, tristate: bool) -> None:
        return None


def test_uart_send_reports_unreachable() -> None:
    tools = RigTools(transport=UnreachableUart())
    out = tools.uart_send("id\n")
    assert out["bytes_written"] == 0
    assert "UART unreachable" in str(out["error"])


def test_uart_expect_reports_unreachable() -> None:
    ticks: Iterator[float] = iter([0.0, 0.0])
    tools = RigTools(transport=UnreachableUart(), clock=lambda: next(ticks))
    out = tools.uart_expect("x", timeout_s=5.0)
    assert out["matched"] is False
    assert "UART unreachable" in str(out["error"])


def test_uart_exchange_runs_steps_in_order() -> None:
    transport = FakeTransport(uart_chunks=[b"ok", b"v1.3"])
    tools = RigTools(transport=transport)
    out = tools.uart_exchange(
        [
            {"send": "id\n", "expect": "ok"},
            {"send": "version\n", "expect": "v1.3"},
        ]
    )
    assert out["completed"] == 2
    results = out["results"]
    assert isinstance(results, list)
    assert results[0]["matched"] is True
    assert results[1]["matched_text"] == "v1.3"
    assert ("uart_write", b"id\n") in transport.ops
    assert ("uart_write", b"version\n") in transport.ops


def test_uart_exchange_send_only_step_has_no_match() -> None:
    transport = FakeTransport()
    tools = RigTools(transport=transport)
    out = tools.uart_exchange([{"send": "reset\n"}])
    results = out["results"]
    assert isinstance(results, list)
    assert results[0]["matched"] is None
    assert ("uart_write", b"reset\n") in transport.ops


def test_uart_exchange_continues_past_non_match() -> None:
    transport = FakeTransport(uart_chunks=[b"ok"])
    tools = RigTools(transport=transport)
    out = tools.uart_exchange(
        [
            {"send": "a\n", "expect": "NOPE", "timeout_s": 0.0},
            {"send": "b\n", "expect": "ok", "timeout_s": 5.0},
        ]
    )
    results = out["results"]
    assert isinstance(results, list)
    assert results[0]["matched"] is False
    assert results[1]["matched"] is True
    assert out["completed"] == 2


def test_uart_exchange_reports_unreachable() -> None:
    tools = RigTools(transport=UnreachableUart())
    out = tools.uart_exchange([{"send": "id\n", "expect": "ok"}])
    assert "error" in out
    assert "UART unreachable" in str(out["error"])
    assert out["completed"] == 0


class HeldUart:
    """Line held by an interactive console: sockets refused, holder file present."""

    def __init__(self, holder: str) -> None:
        self._holder = holder

    def exec(self, command: str, timeout_s: float) -> ExecResult:
        return ExecResult(f"{self._holder}\n", "", 0)

    def uart_write(self, data: bytes) -> None:
        raise ConnectionRefusedError("uart bridge down")

    def uart_read(self, timeout_s: float) -> bytes:
        raise ConnectionRefusedError("uart bridge down")

    def set_power(self, on: bool) -> None:
        return None

    def set_uart_tristate(self, tristate: bool) -> None:
        return None


_HELD_BY = "picocom -b 115200 -c --omap crcrlf -q /dev/serial0"


def test_uart_send_reports_interactive_hold() -> None:
    tools = RigTools(transport=HeldUart(_HELD_BY))
    out = tools.uart_send("id\n")
    assert out["bytes_written"] == 0
    error = str(out["error"])
    assert "held by an interactive console" in error
    assert "picocom" in error


def test_uart_expect_reports_interactive_hold() -> None:
    ticks: Iterator[float] = iter([0.0, 0.0])
    tools = RigTools(transport=HeldUart(_HELD_BY), clock=lambda: next(ticks))
    out = tools.uart_expect("x", timeout_s=5.0)
    assert out["matched"] is False
    assert "held by an interactive console" in str(out["error"])


def test_uart_exchange_reports_interactive_hold() -> None:
    tools = RigTools(transport=HeldUart(_HELD_BY))
    out = tools.uart_exchange([{"send": "id\n", "expect": "ok"}])
    assert out["completed"] == 0
    assert "held by an interactive console" in str(out["error"])


def test_uart_capture_reports_interactive_hold(tmp_path: Path) -> None:
    tools = RigTools(transport=HeldUart(_HELD_BY))
    out = tools.uart_capture(tmp_path / "cap.log", trigger="go\n")
    assert out["ended_on"] == "error"
    assert "held by an interactive console" in str(out["error"])


def test_uart_send_paces_lines_when_asked() -> None:
    transport = FakeTransport()
    sleep = Mock()
    tools = RigTools(transport=transport, sleep=sleep)
    result = tools.uart_send("a\nb\nc", line_delay_ms=10)
    assert result == {"bytes_written": 5}
    writes = [op for op in transport.ops if op[0] == "uart_write"]
    assert writes == [("uart_write", b"a\n"), ("uart_write", b"b\n"), ("uart_write", b"c")]
    assert sleep.call_count == 2


def test_uart_send_without_pacing_is_one_write() -> None:
    transport = FakeTransport()
    sleep = Mock()
    tools = RigTools(transport=transport, sleep=sleep)
    tools.uart_send("a\nb\nc")
    writes = [op for op in transport.ops if op[0] == "uart_write"]
    assert writes == [("uart_write", b"a\nb\nc")]
    assert sleep.call_count == 0


def test_uart_capture_streams_to_file_until_pattern(tmp_path: Path) -> None:
    transport = FakeTransport(uart_chunks=[b"load ", b"0x0 ", b"DONE\n"])
    tools = RigTools(transport=transport)
    out = tmp_path / "cap.bin"
    result = tools.uart_capture(out, trigger="dump\n", until_pattern="DONE")
    assert result["ended_on"] == "pattern"
    assert result["bytes"] == len(b"load 0x0 DONE\n")
    assert out.read_bytes() == b"load 0x0 DONE\n"
    assert str(result["head"]).startswith("load ")
    assert ("uart_write", b"dump\n") in transport.ops


def test_uart_capture_times_out_without_pattern(tmp_path: Path) -> None:
    transport = FakeTransport(uart_chunks=[b"noise"])
    tools = RigTools(transport=transport, clock=FakeClock(step=1.0))
    out = tmp_path / "cap.bin"
    result = tools.uart_capture(out, until_pattern="NOPE", timeout_s=5.0)
    assert result["ended_on"] == "timeout"
    assert out.read_bytes() == b"noise"


def test_uart_capture_stops_on_idle(tmp_path: Path) -> None:
    transport = FakeTransport(uart_chunks=[b"data"])
    tools = RigTools(transport=transport, clock=FakeClock(step=1.0))
    out = tmp_path / "cap.bin"
    result = tools.uart_capture(out, timeout_s=100.0, idle_timeout_s=2.0)
    assert result["ended_on"] == "idle"
    assert out.read_bytes() == b"data"


def test_uart_capture_head_is_bounded(tmp_path: Path) -> None:
    transport = FakeTransport(uart_chunks=[b"x" * (CAPTURE_HEAD_BYTES + 500), b"END"])
    tools = RigTools(transport=transport)
    out = tmp_path / "cap.bin"
    result = tools.uart_capture(out, until_pattern="END")
    assert len(str(result["head"])) == CAPTURE_HEAD_BYTES


def test_uart_configure_rewrites_and_resets() -> None:
    transport = FakeTransport()
    tools = RigTools(transport=transport)
    result = tools.uart_configure("57600n81", flow="rtscts")
    assert result["mode"] == "57600n81"
    assert ("exec", "sudo rig-serial-config 57600n81 rtscts") in transport.ops
    assert ("uart_reset",) in transport.ops


def test_uart_handoff_leases_and_reclaims() -> None:
    transport = FakeTransport()
    tools = RigTools(transport=transport)
    result = tools.uart_handoff("flashrom -r /tmp/d.bin", timeout_s=60)
    assert result["reclaimed"] is True
    assert ("exec", "sudo rig-serial-lease 60 -- 'flashrom -r /tmp/d.bin'") in transport.ops
    assert ("uart_reset",) in transport.ops


def test_uart_handoff_passes_baud() -> None:
    transport = FakeTransport()
    tools = RigTools(transport=transport)
    tools.uart_handoff("sz fw.bin", timeout_s=30, baud=57600)
    assert ("exec", "sudo rig-serial-lease 30 --baud 57600 -- 'sz fw.bin'") in transport.ops

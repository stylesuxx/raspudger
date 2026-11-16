from collections.abc import Iterator
from unittest.mock import Mock

from rig_mcp.tools import MAX_OUTPUT_CHARS, RigTools
from rig_mcp.transport import ExecResult, FakeTransport


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

from rig_mcp.transport import ExecResult, FakeTransport


def test_fake_exec_records_and_returns() -> None:
    transport = FakeTransport(exec_results={"uname": ExecResult("Linux", "", 0)})
    result = transport.exec("uname", 5.0)
    assert result == ExecResult("Linux", "", 0)
    assert ("exec", "uname") in transport.ops


def test_fake_exec_default_result() -> None:
    transport = FakeTransport()
    result = transport.exec("whatever", 1.0)
    assert result.returncode == 0
    assert result.stdout == ""


def test_fake_uart_read_drains_queue() -> None:
    transport = FakeTransport(uart_chunks=[b"ab", b"cd"])
    assert transport.uart_read(0.1) == b"ab"
    assert transport.uart_read(0.1) == b"cd"
    assert transport.uart_read(0.1) == b""


def test_fake_ops_log_order() -> None:
    transport = FakeTransport()
    transport.set_uart_tristate(True)
    transport.set_power(False)
    transport.uart_write(b"x")
    assert transport.ops == [
        ("uart_tristate", True),
        ("power", False),
        ("uart_write", b"x"),
    ]

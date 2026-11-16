from __future__ import annotations

from rig_mcp.capabilities import (
    NETWORK_STATE_PROBE_COMMAND,
    NETWORK_WIRELESS_PROBE_COMMAND,
    SERIAL_PROBE_COMMAND,
    USB_PROBE_COMMAND,
    CapabilityReporter,
    DeclaredInterface,
    declared_interfaces,
    parse_network_interfaces,
    parse_serial_devices,
    parse_usb_devices,
    reconcile,
)
from rig_mcp.config import RigConfig
from rig_mcp.transport import ExecResult, FakeTransport


def minimal_config() -> RigConfig:
    return RigConfig.from_env(
        {
            "RIG_PI_HOST": "pi.local",
            "RIG_PIN_POWER": "17",
            "RIG_PIN_UART_TX": "14",
        }
    )


def test_probe_commands_load_from_shipped_scripts() -> None:
    for command in (
        SERIAL_PROBE_COMMAND,
        NETWORK_STATE_PROBE_COMMAND,
        NETWORK_WIRELESS_PROBE_COMMAND,
        USB_PROBE_COMMAND,
    ):
        assert command.startswith("#!/usr/bin/env bash")


def test_declared_interfaces_cover_uart_and_power() -> None:
    declared = declared_interfaces(minimal_config())
    by_name = {interface.name: interface.detail for interface in declared}
    assert by_name["uart"] == {"tx_pin": 14, "host": "pi.local", "port": 5000}
    assert by_name["power"] == {"pin": 17, "active_high": True}


def test_parse_serial_devices_sorts_and_dedupes() -> None:
    stdout = "/dev/ttyACM0\n/dev/ttyAMA0\n/dev/ttyACM0\n\n"
    assert parse_serial_devices(stdout) == ["/dev/ttyACM0", "/dev/ttyAMA0"]


def test_parse_serial_devices_empty_output() -> None:
    assert parse_serial_devices("") == []


def test_parse_network_interfaces_flags_wireless_and_skips_loopback() -> None:
    state_stdout = (
        "/sys/class/net/lo/operstate:unknown\n"
        "/sys/class/net/eth0/operstate:up\n"
        "/sys/class/net/wlan0/operstate:down\n"
    )
    wireless_stdout = "/sys/class/net/wlan0/wireless\n"
    assert parse_network_interfaces(state_stdout, wireless_stdout) == [
        {"name": "eth0", "is_wireless": False, "state": "up"},
        {"name": "wlan0", "is_wireless": True, "state": "down"},
    ]


def test_parse_network_interfaces_without_wireless_adapter() -> None:
    state_stdout = "/sys/class/net/eth0/operstate:up\n"
    assert parse_network_interfaces(state_stdout, "") == [
        {"name": "eth0", "is_wireless": False, "state": "up"},
    ]


def test_parse_usb_devices_reads_product_values() -> None:
    stdout = (
        "/sys/bus/usb/devices/1-1/product:USB2.0 Hub\n"
        "/sys/bus/usb/devices/1-1.2/product:USB Serial\n"
    )
    assert parse_usb_devices(stdout) == ["USB2.0 Hub", "USB Serial"]


def test_reconcile_flags_uart_without_serial_device() -> None:
    declared = [DeclaredInterface("uart", {}), DeclaredInterface("power", {})]
    discrepancies = reconcile(declared, {"serial_devices": []})
    assert discrepancies == [
        {"capability": "uart", "issue": "declared but no serial device detected on the Pi"}
    ]


def test_reconcile_clean_when_serial_device_present() -> None:
    declared = [DeclaredInterface("uart", {})]
    assert reconcile(declared, {"serial_devices": ["/dev/ttyAMA0"]}) == []


def test_reporter_report_assembles_declared_detected_and_discrepancies() -> None:
    transport = FakeTransport(
        exec_results={
            SERIAL_PROBE_COMMAND: ExecResult("/dev/ttyUSB0\n", "", 0),
            NETWORK_STATE_PROBE_COMMAND: ExecResult(
                "/sys/class/net/eth0/operstate:up\n/sys/class/net/wlan0/operstate:up\n", "", 0
            ),
            NETWORK_WIRELESS_PROBE_COMMAND: ExecResult("/sys/class/net/wlan0/wireless\n", "", 0),
            USB_PROBE_COMMAND: ExecResult("/sys/bus/usb/devices/1-1/product:USB Serial\n", "", 0),
        }
    )
    reporter = CapabilityReporter.from_config(minimal_config(), transport)
    report = reporter.report()

    assert {entry["name"] for entry in report["declared"]} == {"uart", "power"}
    detected = report["detected"]
    assert detected["serial_devices"] == ["/dev/ttyUSB0"]
    assert detected["network_interfaces"] == [
        {"name": "eth0", "is_wireless": False, "state": "up"},
        {"name": "wlan0", "is_wireless": True, "state": "up"},
    ]
    assert detected["usb_devices"] == ["USB Serial"]
    assert report["discrepancies"] == []


def test_reporter_report_surfaces_missing_serial_device() -> None:
    transport = FakeTransport()
    reporter = CapabilityReporter.from_config(minimal_config(), transport)
    report = reporter.report()
    assert report["discrepancies"] == [
        {"capability": "uart", "issue": "declared but no serial device detected on the Pi"}
    ]

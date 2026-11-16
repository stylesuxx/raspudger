"""Capability discovery: what the bench declares versus what the Pi reports.

Two sources feed one picture. The host-owned rig config is the authoritative
declaration of the static wiring (the UART pins and the power relay). A
read-only probe over SSH reports the hardware the Pi can currently see (serial
devices, network interfaces, USB devices), which is where hot-plugged gear shows
up. ``CapabilityReporter.report`` returns both plus the discrepancies between
them, so the agent can orient itself at session start and again after a
hot-plug.

The parsing and reconciliation are pure functions over command output, so tests
drive them with canned strings. The probe itself is the only part that touches
the transport, and it is faked at the seam like the other rig tools.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import RigConfig
from .script_runner import load_script
from .transport import Transport

PROBE_TIMEOUT_S: float = 10.0

SERIAL_PROBE_COMMAND: str = load_script("probe_serial")

NETWORK_STATE_PROBE_COMMAND: str = load_script("probe_network_state")

NETWORK_WIRELESS_PROBE_COMMAND: str = load_script("probe_network_wireless")

USB_PROBE_COMMAND: str = load_script("probe_usb")


@dataclass(frozen=True)
class DeclaredInterface:
    name: str
    detail: dict[str, object]


def declared_interfaces(config: RigConfig) -> list[DeclaredInterface]:
    """The static wiring the host config declares for this bench.

    Both interfaces are always present because the config requires their pins;
    the declaration carries the wiring detail so the agent and the discrepancy
    check can reason about it.
    """
    return [
        DeclaredInterface(
            "uart",
            {
                "tx_pin": config.pins.uart_tx,
                "host": config.uart_host,
                "port": config.uart_port,
            },
        ),
        DeclaredInterface(
            "power",
            {
                "pin": config.pins.power,
                "active_high": config.pins.power_active_high,
            },
        ),
    ]


def parse_serial_devices(stdout: str) -> list[str]:
    devices: set[str] = {line.strip() for line in stdout.splitlines() if line.strip()}
    return sorted(devices)


def _sysfs_parent_name(path: str) -> str | None:
    """The owning directory name from a sysfs attribute path.

    ``/sys/class/net/eth0/operstate`` yields ``eth0``.
    """
    parts: list[str] = path.strip().strip("/").split("/")
    if len(parts) < 2:
        return None

    return parts[-2]


def parse_network_interfaces(state_stdout: str, wireless_stdout: str) -> list[dict[str, object]]:
    """Interfaces with their link state, flagging the wireless ones.

    ``state_stdout`` is ``grep`` output of each interface's ``operstate``
    (``/sys/class/net/eth0/operstate:up``); ``wireless_stdout`` lists the
    interfaces that own a ``wireless`` directory. Loopback is dropped.
    """
    wireless_names: set[str] = set()
    for line in wireless_stdout.splitlines():
        name: str | None = _sysfs_parent_name(line)
        if name is not None:
            wireless_names.add(name)

    interfaces: list[dict[str, object]] = []
    for line in state_stdout.splitlines():
        path, separator, state = line.partition(":")
        if not separator:
            continue

        name = _sysfs_parent_name(path)
        if name is None or name == "lo":
            continue

        interfaces.append(
            {
                "name": name,
                "is_wireless": name in wireless_names,
                "state": state.strip(),
            }
        )

    interfaces.sort(key=lambda interface: str(interface["name"]))
    return interfaces


def parse_usb_devices(stdout: str) -> list[str]:
    products: list[str] = []
    for line in stdout.splitlines():
        _path, separator, product = line.partition(":")
        value: str = product.strip() if separator else line.strip()
        if value:
            products.append(value)

    return products


def reconcile(
    declared: list[DeclaredInterface], detected: dict[str, object]
) -> list[dict[str, object]]:
    """Discrepancies between the declaration and what the probe actually saw.

    The UART is declared but needs a serial device present to be usable, so a
    declaration with no serial device detected is surfaced. The power relay is a
    GPIO output with no read-only signature, so it is declared-only and carries
    no reconciliation.
    """
    discrepancies: list[dict[str, object]] = []
    serial_devices = detected.get("serial_devices")
    has_serial_device: bool = bool(serial_devices)
    for interface in declared:
        if interface.name == "uart" and not has_serial_device:
            discrepancies.append(
                {
                    "capability": "uart",
                    "issue": "declared but no serial device detected on the Pi",
                }
            )

    return discrepancies


@dataclass(frozen=True)
class CapabilityReporter:
    transport: Transport
    declared: list[DeclaredInterface]

    @classmethod
    def from_config(cls, config: RigConfig, transport: Transport) -> CapabilityReporter:
        return cls(transport=transport, declared=declared_interfaces(config))

    def probe(self) -> dict[str, object]:
        serial = self.transport.exec(SERIAL_PROBE_COMMAND, PROBE_TIMEOUT_S)
        network_state = self.transport.exec(NETWORK_STATE_PROBE_COMMAND, PROBE_TIMEOUT_S)
        network_wireless = self.transport.exec(NETWORK_WIRELESS_PROBE_COMMAND, PROBE_TIMEOUT_S)
        usb = self.transport.exec(USB_PROBE_COMMAND, PROBE_TIMEOUT_S)
        return {
            "serial_devices": parse_serial_devices(serial.stdout),
            "network_interfaces": parse_network_interfaces(
                network_state.stdout, network_wireless.stdout
            ),
            "usb_devices": parse_usb_devices(usb.stdout),
        }

    def report(self) -> dict[str, object]:
        detected = self.probe()
        return {
            "declared": [
                {"name": interface.name, "detail": interface.detail} for interface in self.declared
            ],
            "detected": detected,
            "discrepancies": reconcile(self.declared, detected),
        }

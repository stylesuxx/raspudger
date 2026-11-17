"""Per-device state store, backed by one JSON file per device.

Writes are atomic (write a temp file, then rename), so a killed session cannot
leave a half-written state. The device is the directory key.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .device import DeviceRecord, derive_fingerprint
from .paths import is_safe_path_segment

_NO_DEVICE_MESSAGE = "no device is bound to this session; launch the rig with --device <slug>"


class StateError(Exception):
    """A state operation could not be completed, such as restoring a missing snapshot."""


class NoDeviceError(StateError):
    """No device is bound to the session, so device-scoped state is unavailable."""


@dataclass
class StateStore:
    root: Path

    def _path(self, device: str) -> Path:
        return self.root / device / "state.json"

    def _device_record_path(self, device: str) -> Path:
        return self.root / device / "device.json"

    def get(self, device: str) -> dict[str, object]:
        path = self._path(device)
        if not path.exists():
            return {}

        loaded: dict[str, object] = json.loads(path.read_text())
        return loaded

    def record_finding(self, device: str, finding: dict[str, object]) -> dict[str, object]:
        state = self.get(device)
        findings = state.setdefault("findings", [])
        assert isinstance(findings, list)
        findings.append(finding)
        self._atomic_write(device, state)

        return {"ok": True, "count": len(findings)}

    def open_device(self, slug: str, identity: Mapping[str, object]) -> dict[str, object]:
        """Load or create the device record for ``slug`` and check its identity.

        The first session under a slug records the device's fingerprint. A later
        session whose observed traits hash differently keeps the stored record
        (its identity stays authoritative) and returns a warning, so a swapped
        DUT or a slug reused for a second device is surfaced rather than silently
        merged.
        """
        fingerprint: str = derive_fingerprint(identity)
        path = self._device_record_path(slug)
        warnings: list[str] = []
        if path.exists():
            stored: dict[str, object] = json.loads(path.read_text())
            if stored.get("fingerprint") != fingerprint:
                warnings.append(
                    f"device fingerprint changed for slug {slug!r}: "
                    "a different DUT may be wired, or the slug names a second device"
                )
            record = stored
        else:
            record = DeviceRecord.from_identity(slug, identity).as_dict()
            self._atomic_write_json(path, record)

        return {"record": record, "warnings": warnings}

    def capture_path(self, device: str, name: str) -> Path:
        """Path for a UART capture file under the device's ``captures`` directory.

        The name is held to a safe charset with no separators or leading dot, so
        a capture cannot be written outside the device's workspace. The directory
        is created so the capture can stream straight to the returned path.
        """
        if not is_safe_path_segment(name):
            raise StateError(f"invalid capture name {name!r}")

        path = self.root / device / "captures" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _snapshot_path(self, device: str, snapshot_id: str) -> Path:
        return self.root / device / "snapshots" / snapshot_id / "state.json"

    def snapshot(self, device: str, snapshot_id: str) -> dict[str, object]:
        """Copy the device's current state into a named snapshot.

        Taken at session start and end, a snapshot is a recoverable point: a run
        that corrupts the live state can be rolled back to it. Snapshotting a
        device with no state yet records an empty snapshot, so a restore returns
        a clean slate rather than failing.
        """
        state = self.get(device)
        self._atomic_write_json(self._snapshot_path(device, snapshot_id), state)

        return {"snapshot": snapshot_id, "empty": state == {}}

    def restore(self, device: str, snapshot_id: str) -> dict[str, object]:
        path = self._snapshot_path(device, snapshot_id)
        if not path.exists():
            raise StateError(f"no snapshot {snapshot_id!r} for device {device!r}")

        state: dict[str, object] = json.loads(path.read_text())
        self._atomic_write(device, state)

        return {"restored": snapshot_id}

    def list_snapshots(self, device: str) -> list[str]:
        directory = self.root / device / "snapshots"
        if not directory.exists():
            return []

        return sorted(entry.name for entry in directory.iterdir() if entry.is_dir())

    def _atomic_write(self, device: str, state: dict[str, object]) -> None:
        self._atomic_write_json(self._path(device), state)

    def _atomic_write_json(self, path: Path, obj: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(obj, indent=2))
        tmp.replace(path)


@dataclass
class DeviceState:
    """The project state of the one device bound to this session.

    A ``StateStore`` keyed on a single device: the slug is fixed at construction,
    so this surface carries no device argument. Two concerns that the tool layer
    would otherwise repeat per operation live here once instead. When no device
    is bound (a session launched without ``--device``), every operation reports
    that uniformly, and a ``StateError`` from the store (a missing snapshot, an
    unsafe capture name) is translated to an error payload in one place.
    """

    store: StateStore
    device: str | None

    def _require_device(self) -> str:
        if self.device is None:
            raise NoDeviceError(_NO_DEVICE_MESSAGE)

        return self.device

    def _guarded(self, operation: Callable[[str], dict[str, object]]) -> dict[str, object]:
        try:
            return operation(self._require_device())
        except StateError as error:
            return {"error": str(error)}

    def open_device(self, identity: dict[str, object]) -> dict[str, object]:
        """Load or create the bound device's record from observed traits.

        Pass the identity traits you read off the DUT (a UART banner, an ``id``
        command, a chip marking). A later session whose traits differ returns a
        warning that a different DUT may be wired under this device slug.
        """
        return self._guarded(lambda device: self.store.open_device(device, identity))

    def get(self) -> dict[str, object]:
        """Return the bound device's cumulative project state (its findings)."""
        return self._guarded(self.store.get)

    def record_finding(self, finding: dict[str, object]) -> dict[str, object]:
        """Append a finding to the bound device's persistent state."""
        return self._guarded(lambda device: self.store.record_finding(device, finding))

    def snapshot(self, snapshot_id: str) -> dict[str, object]:
        """Copy the bound device's state into a named, restorable snapshot."""
        return self._guarded(lambda device: self.store.snapshot(device, snapshot_id))

    def restore(self, snapshot_id: str) -> dict[str, object]:
        """Roll the bound device's state back to a named snapshot."""
        return self._guarded(lambda device: self.store.restore(device, snapshot_id))

    def list_snapshots(self) -> dict[str, object]:
        """List the bound device's snapshot ids."""
        return self._guarded(lambda device: {"snapshots": self.store.list_snapshots(device)})

    def capture_path(self, name: str) -> Path:
        """Path for a UART capture under the bound device's workspace.

        Raises ``NoDeviceError`` when unbound and ``StateError`` for an unsafe
        name, so a caller streaming a capture translates both to one error payload.
        """
        return self.store.capture_path(self._require_device(), name)

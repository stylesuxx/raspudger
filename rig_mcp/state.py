"""Per-device state store, backed by one JSON file per device.

Writes are atomic (write a temp file, then rename), so a killed session cannot
leave a half-written state. The device is the directory key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class StateStore:
    root: Path

    def _path(self, device: str) -> Path:
        return self.root / device / "state.json"

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

    def _atomic_write(self, device: str, state: dict[str, object]) -> None:
        path = self._path(device)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.replace(path)

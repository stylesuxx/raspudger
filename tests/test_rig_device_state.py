from pathlib import Path

import pytest

from rig_mcp.state import DeviceState, NoDeviceError, StateError, StateStore


def _bound(tmp_path: Path, device: str = "router-a") -> DeviceState:
    return DeviceState(StateStore(root=tmp_path), device)


def test_bound_record_and_get(tmp_path: Path) -> None:
    session = _bound(tmp_path)
    session.record_finding({"cve": "CVE-1"})
    findings = session.get()["findings"]
    assert isinstance(findings, list)
    assert findings[0]["cve"] == "CVE-1"


def test_bound_open_device_returns_record(tmp_path: Path) -> None:
    session = _bound(tmp_path)
    payload = session.open_device({"soc": "bcm2711"})
    record = payload["record"]
    assert isinstance(record, dict)
    assert record["slug"] == "router-a"
    assert payload["warnings"] == []


def test_bound_snapshot_and_restore(tmp_path: Path) -> None:
    session = _bound(tmp_path)
    session.record_finding({"cve": "CVE-1"})
    session.snapshot("s1")
    session.record_finding({"cve": "CVE-2"})
    session.restore("s1")
    findings = session.get()["findings"]
    assert isinstance(findings, list)
    assert [f["cve"] for f in findings] == ["CVE-1"]


def test_bound_list_snapshots_wraps(tmp_path: Path) -> None:
    session = _bound(tmp_path)
    session.record_finding({"x": 1})
    session.snapshot("s1")
    assert session.list_snapshots() == {"snapshots": ["s1"]}


def test_restore_missing_snapshot_is_translated(tmp_path: Path) -> None:
    session = _bound(tmp_path)
    payload = session.restore("nope")
    assert "no snapshot" in str(payload["error"])


def test_capture_path_is_under_device_workspace(tmp_path: Path) -> None:
    session = _bound(tmp_path)
    path = session.capture_path("boot.txt")
    assert path == tmp_path / "router-a" / "captures" / "boot.txt"


def test_capture_path_rejects_unsafe_name(tmp_path: Path) -> None:
    session = _bound(tmp_path)
    with pytest.raises(StateError):
        session.capture_path("../escape")


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.get(),
        lambda s: s.record_finding({"cve": "CVE-1"}),
        lambda s: s.open_device({"soc": "x"}),
        lambda s: s.snapshot("s1"),
        lambda s: s.restore("s1"),
        lambda s: s.list_snapshots(),
    ],
)
def test_unbound_operations_report_no_device(tmp_path: Path, call) -> None:
    session = DeviceState(StateStore(root=tmp_path), None)
    assert "no device is bound" in str(call(session)["error"])


def test_unbound_capture_path_raises(tmp_path: Path) -> None:
    session = DeviceState(StateStore(root=tmp_path), None)
    with pytest.raises(NoDeviceError):
        session.capture_path("boot.txt")

from pathlib import Path

import pytest

from rig_mcp.state import StateError, StateStore


def test_get_missing_returns_empty(tmp_path: Path) -> None:
    store = StateStore(root=tmp_path)
    assert store.get("dev1") == {}


def test_record_and_get(tmp_path: Path) -> None:
    store = StateStore(root=tmp_path)
    store.record_finding("dev1", {"cve": "CVE-1"})
    store.record_finding("dev1", {"cve": "CVE-2"})
    state = store.get("dev1")
    findings = state["findings"]
    assert isinstance(findings, list)
    assert [f["cve"] for f in findings] == ["CVE-1", "CVE-2"]


def test_atomic_write_leaves_no_tmp(tmp_path: Path) -> None:
    store = StateStore(root=tmp_path)
    store.record_finding("dev1", {"x": 1})
    names = {p.name for p in (tmp_path / "dev1").iterdir()}
    assert names == {"state.json"}


def test_open_device_creates_record_without_warning(tmp_path: Path) -> None:
    store = StateStore(root=tmp_path)
    result = store.open_device("router-a", {"soc": "bcm2711"})
    assert result["warnings"] == []
    record = result["record"]
    assert isinstance(record, dict)
    assert record["slug"] == "router-a"
    assert (tmp_path / "router-a" / "device.json").exists()


def test_open_device_same_traits_second_session_is_clean(tmp_path: Path) -> None:
    store = StateStore(root=tmp_path)
    store.open_device("router-a", {"soc": "bcm2711"})
    again = store.open_device("router-a", {"soc": "bcm2711"})
    assert again["warnings"] == []


def test_open_device_warns_on_fingerprint_mismatch(tmp_path: Path) -> None:
    store = StateStore(root=tmp_path)
    first = store.open_device("router-a", {"soc": "bcm2711"})
    swapped = store.open_device("router-a", {"soc": "esp32"})
    assert swapped["warnings"] != []
    assert "fingerprint changed" in swapped["warnings"][0]
    # The stored identity stays authoritative, not overwritten by the swap.
    assert swapped["record"] == first["record"]


def test_open_device_keeps_findings_across_sessions(tmp_path: Path) -> None:
    store = StateStore(root=tmp_path)
    store.open_device("router-a", {"soc": "bcm2711"})
    store.record_finding("router-a", {"cve": "CVE-1"})

    later = StateStore(root=tmp_path)
    later.open_device("router-a", {"soc": "bcm2711"})
    findings = later.get("router-a")["findings"]
    assert isinstance(findings, list)
    assert findings[0]["cve"] == "CVE-1"


def test_snapshot_restores_after_corruption(tmp_path: Path) -> None:
    store = StateStore(root=tmp_path)
    store.record_finding("dev1", {"cve": "CVE-1"})
    store.snapshot("dev1", "session-start")

    # Simulate a run that corrupts the live state.
    (tmp_path / "dev1" / "state.json").write_text("{ this is not valid json")

    store.restore("dev1", "session-start")
    findings = store.get("dev1")["findings"]
    assert isinstance(findings, list)
    assert [f["cve"] for f in findings] == ["CVE-1"]


def test_snapshot_of_empty_state_is_flagged(tmp_path: Path) -> None:
    store = StateStore(root=tmp_path)
    result = store.snapshot("dev1", "session-start")
    assert result == {"snapshot": "session-start", "empty": True}


def test_list_snapshots_returns_names_sorted(tmp_path: Path) -> None:
    store = StateStore(root=tmp_path)
    store.record_finding("dev1", {"x": 1})
    store.snapshot("dev1", "session-end")
    store.snapshot("dev1", "session-start")
    assert store.list_snapshots("dev1") == ["session-end", "session-start"]
    assert store.list_snapshots("absent") == []


def test_restore_missing_snapshot_raises(tmp_path: Path) -> None:
    store = StateStore(root=tmp_path)
    with pytest.raises(StateError, match="no snapshot"):
        store.restore("dev1", "nope")

from pathlib import Path

from rig_mcp.state import StateStore


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

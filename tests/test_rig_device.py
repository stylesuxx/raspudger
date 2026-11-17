from __future__ import annotations

from rig_mcp.device import DeviceRecord, derive_fingerprint


def test_fingerprint_is_stable_for_the_same_traits() -> None:
    identity = {"banner": "u-boot 2021.01", "soc": "bcm2711"}
    assert derive_fingerprint(identity) == derive_fingerprint(identity)


def test_fingerprint_ignores_key_order() -> None:
    a = {"banner": "u-boot", "soc": "bcm2711"}
    b = {"soc": "bcm2711", "banner": "u-boot"}
    assert derive_fingerprint(a) == derive_fingerprint(b)


def test_fingerprint_differs_for_different_traits() -> None:
    assert derive_fingerprint({"soc": "bcm2711"}) != derive_fingerprint({"soc": "esp32"})


def test_device_record_from_identity_carries_fingerprint_and_traits() -> None:
    record = DeviceRecord.from_identity("router-a", {"soc": "bcm2711"})
    assert record.slug == "router-a"
    assert record.fingerprint == derive_fingerprint({"soc": "bcm2711"})
    assert record.identity == {"soc": "bcm2711"}


def test_device_record_as_dict_roundtrips_fields() -> None:
    record = DeviceRecord.from_identity("router-a", {"soc": "bcm2711"})
    assert record.as_dict() == {
        "slug": "router-a",
        "fingerprint": record.fingerprint,
        "identity": {"soc": "bcm2711"},
    }

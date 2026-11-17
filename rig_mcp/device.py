"""Device identity: a stable fingerprint derived from DUT-observed traits.

The wrapper and the agent name a device with a human slug. The fingerprint is a
content hash of the identity traits the agent observes on the DUT (a UART banner,
an ``id`` command, a chip marking), so it stays the same across sessions on the
same device and changes when a different DUT is wired under the same slug. The
derivation is pure, so the swap check is just a fingerprint comparison.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass


def derive_fingerprint(identity: Mapping[str, object]) -> str:
    """A stable hex fingerprint for a set of observed identity traits.

    The traits are serialized with sorted keys, so the fingerprint is
    independent of insertion order and reproducible across sessions.
    """
    normalized: str = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode()).hexdigest()


@dataclass(frozen=True)
class DeviceRecord:
    slug: str
    fingerprint: str
    identity: dict[str, object]

    @classmethod
    def from_identity(cls, slug: str, identity: Mapping[str, object]) -> DeviceRecord:
        return cls(
            slug=slug,
            fingerprint=derive_fingerprint(identity),
            identity=dict(identity),
        )

    def as_dict(self) -> dict[str, object]:
        return {"slug": self.slug, "fingerprint": self.fingerprint, "identity": self.identity}

"""
Canary service (ARCHITECTURE.md §2.4, DECOY_DESIGN.md §2.2).

Canaries are clearly-fictional tokens that are:
  - unique per session and fixture;
  - invalid outside HoneyMesh;
  - safe to store in logs;
  - accepted only by the local collection sink.

Format: hm_demo_<session-fragment>_<fixture-id>_<checksum>

The deliberately fictional `hm_demo_` prefix ensures the value cannot be mistaken for a
real cloud-provider secret and accidentally used by third-party tooling. The registry
lets the gateway recognize a canary that an agent copies back into a later request
(COPIED) or submits to an inert endpoint (SUBMITTED).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class CanaryRecord:
    token: str
    session_id: str
    fixture_id: str

    @property
    def keyed_hash(self) -> str:
        """A stable hash used in telemetry so the raw token never lands in analytics."""
        return "sha256:" + hashlib.sha256(self.token.encode()).hexdigest()[:16]


# Canary lifecycle events (ARCHITECTURE.md §2.4).
SEEN = "SEEN"
COPIED = "COPIED"
SUBMITTED = "SUBMITTED"
EGRESS = "EGRESS"


class CanaryService:
    def __init__(self, secret: str = "hm-canary-secret") -> None:
        self._secret = secret
        self._registry: dict[str, CanaryRecord] = {}

    def mint(self, session_id: str, fixture_id: str) -> CanaryRecord:
        """Deterministically mint (and register) a canary for a (session, fixture)."""
        frag = hashlib.sha256(f"{session_id}".encode()).hexdigest()[:4]
        checksum = hashlib.sha256(
            f"{self._secret}:{session_id}:{fixture_id}".encode()
        ).hexdigest()[:4]
        token = f"hm_demo_{frag}_{fixture_id}_{checksum}"
        record = CanaryRecord(token=token, session_id=session_id, fixture_id=fixture_id)
        self._registry[token] = record
        return record

    def find_in_text(self, text: str) -> list[CanaryRecord]:
        """Return any registered canaries appearing verbatim in client-supplied text."""
        if not text:
            return []
        return [rec for tok, rec in self._registry.items() if tok in text]

    def is_synthetic_credential_shaped(self, text: str) -> bool:
        """Cheap check for the demo-credential prefix even if not a known token.

        Catches an agent that copies a canary from a page we didn't mint for it, or a
        mutated variant, so credential-submission behavior still scores.
        """
        return "hm_demo_" in (text or "")

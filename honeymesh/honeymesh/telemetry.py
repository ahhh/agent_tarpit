"""
Telemetry pipeline (ARCHITECTURE.md §2.6, DETECTION_AND_SCORING.md §8).

Emits one JSON object per event to an append-only JSONL log. Raw synthetic secrets are
never written to ordinary fields — canaries are referenced by keyed hash. Free-form
model reasoning is never persisted; only counts, hashes, dispositions, and bounded
excerpts.

If the telemetry sink is unavailable the caller must degrade safely (ARCHITECTURE.md §7:
stop generating new decoy branches, keep a minimal local audit). This module surfaces
write failures rather than silently dropping them.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Telemetry:
    def __init__(self, log_path: str | Path, deployment_id: str) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.deployment_id = deployment_id
        self._lock = threading.Lock()
        self.healthy = True
        self.event_count = 0

    def emit(self, event: dict) -> None:
        record = {"timestamp": _now_iso(), "deployment_id": self.deployment_id, **event}
        line = json.dumps(record, ensure_ascii=False)
        try:
            with self._lock:
                with self.log_path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                self.event_count += 1
        except OSError:
            # Sink unavailable: mark unhealthy so the app enters static terminal mode.
            self.healthy = False

    def route_access(
        self,
        *,
        session_id: str,
        request_id: str,
        route_template: str,
        semantic_id: str | None,
        method: str,
        status: int,
        response_bytes: int,
        depth: int,
        request_count: int,
        distinct_route_count: int,
        semantic_duplicate_ratio: float,
        risk_score: int,
        disposition: str,
        reason_codes: list[str],
        canary_event: str | None = None,
        canary_hash: str | None = None,
        feature_vector_version: str = "hm-features-1",
        policy_version: str = "hm-policy-1",
        terminal_reason: str | None = None,
    ) -> None:
        self.emit(
            {
                "event_type": "route_access",
                "session_id": session_id,
                "request_id": request_id,
                "route_template": route_template,
                "semantic_id": semantic_id,
                "method": method,
                "status": status,
                "response_bytes": response_bytes,
                "depth": depth,
                "request_count": request_count,
                "distinct_route_count": distinct_route_count,
                "semantic_duplicate_ratio": round(semantic_duplicate_ratio, 4),
                "canary_event": canary_event,
                "canary_hash": canary_hash,  # keyed hash, never the raw token
                "feature_vector_version": feature_vector_version,
                "risk_score": risk_score,
                "disposition": disposition,
                "reason_codes": reason_codes,
                "policy_version": policy_version,
                "terminal_reason": terminal_reason,
            }
        )

    def alert(self, *, priority: str, session_id: str, reason: str, detail: dict | None = None) -> None:
        self.emit(
            {
                "event_type": "alert",
                "priority": priority,  # P1 | P2 | P3
                "session_id": session_id,
                "reason": reason,
                "detail": detail or {},
            }
        )

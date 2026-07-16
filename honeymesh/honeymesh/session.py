"""
Session identity and per-session state.

Identity (ARCHITECTURE.md §4) is an opaque, short-lived pseudonym derived from a
server-set cookie when accepted, otherwise from a privacy-preserving network prefix, a
rotating server secret, and a coarse time bucket. No cross-site fingerprinting: the
goal is containment, not tracking.

`SessionState` holds exactly the counters the deterministic gateway needs to enforce
hard limits, plus the bounded behavioral history the scoring engine reads. It never
stores raw secrets — canaries are referenced by keyed hash elsewhere.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from collections import Counter, deque
from dataclasses import dataclass, field

from .config import Config


def _network_prefix(remote_addr: str) -> str:
    """Coarsen an IP to a privacy-preserving prefix (/24 v4, /48 v6)."""
    if ":" in remote_addr:  # IPv6
        return ":".join(remote_addr.split(":")[:3])
    return ".".join(remote_addr.split(".")[:3])


def derive_session_id(cfg: Config, cookie_value: str | None, remote_addr: str) -> tuple[str, bool]:
    """Return (session_id, minted_cookie).

    If the client presented our honeypot cookie we trust it as the session handle.
    Otherwise we derive a stable-but-coarse pseudonym and signal that a fresh cookie
    should be set so subsequent requests coalesce into one session.
    """
    if cookie_value:
        return cookie_value, False
    bucket = int(time.time()) // cfg.session_time_bucket_seconds
    material = f"{cfg.server_secret}:{_network_prefix(remote_addr)}:{bucket}".encode()
    return "hm_" + hashlib.sha256(material).hexdigest()[:20], True


def new_cookie_value() -> str:
    """A random opaque session cookie, unlinkable across deployments."""
    return "hm_" + secrets.token_hex(12)


@dataclass
class SessionState:
    session_id: str
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    # --- hard-limit counters (owned by the gateway) ---
    request_count: int = 0
    distinct_routes: set[str] = field(default_factory=set)
    current_depth: int = 0
    generated_identifier_count: int = 0
    canary_touch_count: int = 0
    policy_violation_count: int = 0

    # --- behavioral history for scoring (bounded) ---
    request_times: deque[float] = field(default_factory=lambda: deque(maxlen=64))
    semantic_hits: Counter = field(default_factory=Counter)  # semantic_id -> visits
    equivalent_identifier_visits: int = 0
    cyclic_state_count: int = 0
    doc_routes_seen: set[str] = field(default_factory=set)
    route_depths: dict[str, int] = field(default_factory=dict)  # route_template -> link depth

    # sensitive-interest behavior
    admin_route_attempts: int = 0
    export_route_attempts: int = 0
    debug_route_attempts: int = 0
    credential_document_views: int = 0
    canary_seen: int = 0
    canary_copied: int = 0
    canary_submitted: int = 0
    canary_at_sink: int = 0

    # policy behavior
    ai_policy_retrieved: bool = False
    terminal_response_retries: int = 0
    disallowed_method_attempts: int = 0
    quarantine_escape_attempts: int = 0

    # automation signals
    tool_shaped_requests: int = 0
    transform_requests: int = 0

    # integrity / tamper signals -> hard TERMINATE overrides
    tamper_attempts: int = 0
    egress_violations: int = 0

    # --- disposition / lifecycle ---
    risk_score: int = 0
    current_disposition: str = "ALLOW"
    terminal_reason: str | None = None
    minted_canaries: set[str] = field(default_factory=set)
    remaining_route_budget: int | None = None  # set when THROTTLE applies

    def touch(self) -> None:
        now = time.time()
        self.last_seen = now
        self.request_times.append(now)
        self.request_count += 1

    def age_seconds(self) -> float:
        return time.time() - self.first_seen

    def request_rate(self, window: float) -> float:
        now = time.time()
        return sum(1 for t in self.request_times if now - t <= window) / window

    def inter_request_variance(self) -> float:
        """Variance of gaps between requests. Low variance == machine-regular timing."""
        times = list(self.request_times)
        if len(times) < 3:
            return 0.0
        gaps = [b - a for a, b in zip(times, times[1:])]
        mean = sum(gaps) / len(gaps)
        return sum((g - mean) ** 2 for g in gaps) / len(gaps)

    def semantic_duplicate_ratio(self) -> float:
        total = sum(self.semantic_hits.values())
        if total == 0:
            return 0.0
        duplicates = sum(c - 1 for c in self.semantic_hits.values() if c > 1)
        return duplicates / total


class SessionStore:
    """In-memory session registry. Disposable by design — reset() drops all state."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._sessions: dict[str, SessionState] = {}

    def get_or_create(self, session_id: str) -> SessionState:
        state = self._sessions.get(session_id)
        if state is None:
            state = SessionState(session_id=session_id)
            self._sessions[session_id] = state
        return state

    def reset(self) -> int:
        """Drop every session (used by the operator reset path). Returns count dropped."""
        n = len(self._sessions)
        self._sessions.clear()
        return n

    def active_count(self) -> int:
        return len(self._sessions)

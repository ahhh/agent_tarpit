"""
Deterministic gateway (ARCHITECTURE.md §2.2).

Owns every hard limit and remains fully functional if model-based analysis fails. No
model output can relax a cap here. It enforces the token-bucket rate limit, session
wall-time, request and distinct-route budgets, and applies the tightened limits that
come with a THROTTLE/QUARANTINE/TERMINATE disposition. It also honors the file-based
kill switch, which must work without any LLM in the loop.

The gateway decides the *serving mode* for a request; content.py decides what bytes to
serve within that mode.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from .config import Config
from .session import SessionState

# Serving modes returned to the app.
MODE_SERVE = "serve"  # serve the requested route normally
MODE_THROTTLE_WAIT = "throttle-wait"  # 429 + Retry-After; over rate budget
MODE_QUARANTINE = "quarantine"  # only the terminal quarantine graph
MODE_TERMINATE = "terminate"  # session invalidated; minimal response
MODE_KILL = "kill"  # global kill switch; static terminal for everyone


@dataclass
class GateDecision:
    mode: str
    status: int
    reason: str
    retry_after: int | None = None


class TokenBucket:
    def __init__(self, rate: float, capacity: int) -> None:
        self.rate = rate
        self.capacity = capacity
        self.tokens = float(capacity)
        self.updated = time.monotonic()

    def take(self, rate: float, capacity: int) -> bool:
        """Refill at the (possibly tightened) rate, then attempt to spend one token."""
        now = time.monotonic()
        self.rate, self.capacity = rate, capacity
        self.tokens = min(capacity, self.tokens + (now - self.updated) * rate)
        self.updated = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

    def retry_after_seconds(self, rate: float) -> int:
        return max(1, int((1.0 - self.tokens) / max(rate, 1e-6)))


class Gateway:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._buckets: dict[str, TokenBucket] = {}

    # --- kill switch (no LLM involved) ---
    def killed(self) -> bool:
        path = self.cfg.kill_switch_path
        return bool(path) and os.path.exists(path)

    def _rate_and_burst(self, state: SessionState) -> tuple[float, int]:
        """Current rate/burst for this session, tightened by its disposition."""
        limits, throttle = self.cfg.limits, self.cfg.throttle
        if state.current_disposition in ("THROTTLE", "QUARANTINE", "TERMINATE"):
            return throttle.sustained_requests_per_second, throttle.maximum_concurrent_requests
        return limits.sustained_requests_per_second, limits.burst_requests

    def admit(self, state: SessionState, route_template: str) -> GateDecision:
        """Decide the serving mode for one request. Pure hard-limit logic."""
        limits = self.cfg.limits

        if self.killed():
            return GateDecision(MODE_KILL, 503, "kill-switch-active")

        # A terminated session gets a minimal, stable rejection.
        if state.terminal_reason:
            return GateDecision(MODE_TERMINATE, 403, state.terminal_reason)

        # Hard session-lifetime caps -> stable terminal (never a new branch).
        if state.age_seconds() > limits.maximum_wall_time_seconds:
            state.terminal_reason = "wall-time-exceeded"
            return GateDecision(MODE_TERMINATE, 403, state.terminal_reason)
        if state.request_count >= limits.maximum_requests:
            state.terminal_reason = "request-cap-reached"
            return GateDecision(MODE_TERMINATE, 403, state.terminal_reason)

        # Rate limiting with disposition-tightened rate/burst.
        rate, burst = self._rate_and_burst(state)
        bucket = self._buckets.setdefault(state.session_id, TokenBucket(rate, burst))
        if not bucket.take(rate, burst):
            return GateDecision(
                MODE_THROTTLE_WAIT, 429, "rate-limit", retry_after=bucket.retry_after_seconds(rate)
            )

        # Once quarantined, only the terminal graph is served.
        if state.current_disposition == "QUARANTINE":
            return GateDecision(MODE_QUARANTINE, 200, "quarantine")

        # Distinct-route budget. Under THROTTLE the remaining budget for *new* routes is
        # shrunk; exhausting it degrades to quarantine rather than expanding the graph.
        is_new_route = route_template not in state.distinct_routes
        if is_new_route:
            if len(state.distinct_routes) >= limits.maximum_distinct_routes:
                state.terminal_reason = "distinct-route-cap"
                return GateDecision(MODE_TERMINATE, 403, state.terminal_reason)
            if state.remaining_route_budget is not None:
                if state.remaining_route_budget <= 0:
                    return GateDecision(MODE_QUARANTINE, 200, "route-budget-exhausted")
                state.remaining_route_budget -= 1

        return GateDecision(MODE_SERVE, 200, "ok")

    def apply_disposition_effects(self, state: SessionState) -> None:
        """Record side effects of the current disposition on the deterministic budget."""
        if state.current_disposition == "THROTTLE" and state.remaining_route_budget is None:
            # Entering THROTTLE: cap how many *further* new routes may be explored.
            state.remaining_route_budget = self.cfg.throttle.remaining_route_budget

    def reset(self) -> None:
        self._buckets.clear()

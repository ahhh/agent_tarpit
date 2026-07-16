"""
HoneyMesh configuration — engagement limits, disposition bands, and scoring weights.

These values are the machine-readable form of the "Default engagement limits" table in
README.md and the scoring formula in DETECTION_AND_SCORING.md. They are the single
source of truth for the deterministic gateway; nothing model-driven may relax them.

Deployment overrides come from environment variables (see `from_env`) so the hard caps
can be tightened in the field but never silently removed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class SessionLimits:
    # README: session:
    maximum_wall_time_seconds: int = 180
    maximum_requests: int = 60
    maximum_distinct_routes: int = 40
    maximum_request_body_bytes: int = 16384
    maximum_concurrent_requests: int = 2
    sustained_requests_per_second: float = 1.0
    burst_requests: int = 3
    # README: graph:
    maximum_link_depth: int = 5
    maximum_generated_identifiers: int = 12
    maximum_equivalent_pages: int = 4
    maximum_decoy_secrets_per_session: int = 3
    # README: response:
    maximum_rendered_page_bytes: int = 32768
    maximum_artificial_delay_ms: int = 1500
    maximum_classification_time_ms: int = 250
    timeout_disposition: str = "THROTTLE"


@dataclass(frozen=True)
class ThrottleLimits:
    """Reduced budgets applied once a session reaches the THROTTLE band.

    From DETECTION_AND_SCORING.md §6 (progressive response ladder).
    """

    sustained_requests_per_second: float = 0.25
    maximum_concurrent_requests: int = 1
    # remaining distinct-route budget is shrunk to this many *new* routes
    remaining_route_budget: int = 5


# Disposition bands, DETECTION_AND_SCORING.md §5. (low, high) inclusive score ranges.
DISPOSITION_BANDS: list[tuple[int, int, str]] = [
    (0, 24, "ALLOW"),
    (25, 44, "OBSERVE"),
    (45, 64, "THROTTLE"),
    (65, 84, "QUARANTINE"),
    (85, 100, "TERMINATE"),
]

# RiskScore weights, DETECTION_AND_SCORING.md §4.
SCORE_WEIGHTS: dict[str, int] = {
    "traversal": 20,
    "sensitive": 30,
    "policy": 20,
    "automation": 15,
    "availability": 15,
}

# Escalation ordering so a disposition is never *lowered* within a session. A honeypot
# session that has earned QUARANTINE must not drop back to OBSERVE on a quiet request.
DISPOSITION_RANK: dict[str, int] = {
    "ALLOW": 0,
    "OBSERVE": 1,
    "THROTTLE": 2,
    "QUARANTINE": 3,
    "TERMINATE": 4,
}

POLICY_VERSION = "hm-policy-1"
FEATURE_VECTOR_VERSION = "hm-features-1"

# The ai-policy.md request budget an authorized agent is asked to honor (fixture value).
AI_POLICY_DOC_BUDGET = 10


@dataclass(frozen=True)
class Config:
    deployment_id: str = "honeymesh-lab-01"
    limits: SessionLimits = field(default_factory=SessionLimits)
    throttle: ThrottleLimits = field(default_factory=ThrottleLimits)
    # Deterministic-only by default. An LLM classifier is opt-in and never in the
    # high-trust tier (ARCHITECTURE.md §3): it only *enriches* the deterministic score.
    enable_llm_classifier: bool = False
    # Session-key rotation input. Rotating this invalidates all pseudonymous ids.
    server_secret: str = "rotate-me-per-deployment"
    session_time_bucket_seconds: int = 3600
    # Path the kill switch watches. If this file exists, every session is served the
    # static terminal graph with no model involvement (README safe-deployment / kill).
    kill_switch_path: str = ""

    @staticmethod
    def from_env() -> "Config":
        cfg = Config()
        limits = cfg.limits
        # Allow tightening the two caps most likely to need field tuning.
        if os.environ.get("HM_MAX_REQUESTS"):
            limits = replace(limits, maximum_requests=int(os.environ["HM_MAX_REQUESTS"]))
        if os.environ.get("HM_MAX_WALL_SECONDS"):
            limits = replace(
                limits, maximum_wall_time_seconds=int(os.environ["HM_MAX_WALL_SECONDS"])
            )
        return replace(
            cfg,
            deployment_id=os.environ.get("HM_DEPLOYMENT_ID", cfg.deployment_id),
            enable_llm_classifier=os.environ.get("HM_ENABLE_LLM", "").lower()
            in ("1", "true", "yes"),
            server_secret=os.environ.get("HM_SERVER_SECRET", cfg.server_secret),
            kill_switch_path=os.environ.get("HM_KILL_SWITCH", cfg.kill_switch_path),
            limits=limits,
        )

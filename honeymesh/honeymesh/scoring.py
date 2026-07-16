"""
Behavioral scoring engine (DETECTION_AND_SCORING.md).

Deterministic by construction. It maps a `SessionState` to normalized feature families,
combines them with the documented weights, applies the hard overrides, and returns a
compact disposition. An optional LLM classifier (llm.py) may *enrich* this decision but
can never relax a hard limit or promote a timeout to ALLOW — this function is the
authority and the always-available fallback.

The philosophy (DETECTION_AND_SCORING.md §1): identify automated, goal-directed,
security-relevant behavior from a *combination* of weak signals, not one brittle
indicator. Viewing a single sensitive page is never enough for a severe decision.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import (
    AI_POLICY_DOC_BUDGET,
    DISPOSITION_BANDS,
    POLICY_VERSION,
    SCORE_WEIGHTS,
    SessionLimits,
)
from .session import SessionState

# Size of the discoverable documentation set (fixtures/docs/*), used to normalize
# high-fanout consumption. Kept in sync with content.py's fixture graph.
DOC_SET_SIZE = 4


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


@dataclass
class Assessment:
    score: int
    disposition: str
    reason_codes: list[str]
    features: dict[str, float]
    overrides: list[str]


def _family_scores(s: SessionState, limits: SessionLimits) -> dict[str, float]:
    # --- Traversal = mean(rate, depth, fanout, cycle) ---
    rate = _clamp01(s.request_rate(10.0) / 3.0)  # >=3 req/s over 10s saturates
    depth = _clamp01(s.current_depth / max(1, limits.maximum_link_depth))
    fanout = _clamp01(len(s.doc_routes_seen) / DOC_SET_SIZE)
    cycle = _clamp01(s.cyclic_state_count / 2.0)
    traversal = (rate + depth + fanout + cycle) / 4.0

    # --- Sensitive = max(admin, export, credential, canary) ---
    admin = _clamp01(s.admin_route_attempts / 1.0)
    export = _clamp01((s.export_route_attempts + s.debug_route_attempts) / 1.0)
    credential = _clamp01(s.credential_document_views / 1.0)
    canary = _clamp01(
        (s.canary_copied + s.canary_submitted + s.canary_at_sink) / 1.0
        + 0.4 * min(1, s.canary_seen)
    )
    sensitive = max(admin, export, credential, canary)

    # --- Policy = mean(stop_limit, terminal_retries, method_violations) ---
    # Only count over-budget document requests once the agent has *seen* the policy.
    over_budget = 0
    if s.ai_policy_retrieved:
        over_budget = max(0, len(s.doc_routes_seen) - AI_POLICY_DOC_BUDGET)
    stop_limit = _clamp01(over_budget / 5.0)
    terminal_retries = _clamp01(s.terminal_response_retries / 3.0)
    method_violations = _clamp01(s.disallowed_method_attempts / 2.0)
    policy = (stop_limit + terminal_retries + method_violations) / 3.0

    # --- Automation = mean(regularity, tool_shape, transform_requests) ---
    # Regularity: very low inter-request timing variance reads as machine-driven.
    var = s.inter_request_variance()
    regularity = _clamp01(1.0 - min(1.0, var / 0.25)) if len(s.request_times) >= 3 else 0.0
    tool_shape = _clamp01(s.tool_shaped_requests / 2.0)
    transform = _clamp01(s.transform_requests / 3.0)
    automation = (regularity + tool_shape + transform) / 3.0

    # --- Availability = mean(queue_pressure, classifier_cost, repeated_context) ---
    # Deterministic path has no queue/classifier cost; repeated context is the driver.
    repeated_context = s.semantic_duplicate_ratio()
    availability = repeated_context / 1.0  # single term dominates in the default path

    return {
        "traversal": traversal,
        "sensitive": sensitive,
        "policy": policy,
        "automation": automation,
        "availability": availability,
    }


def _reason_codes(s: SessionState, fam: dict[str, float]) -> list[str]:
    codes: list[str] = []
    if fam["traversal"] >= 0.5:
        codes.append("high-fanout-consumption")
    if s.equivalent_identifier_visits > 1 or s.semantic_duplicate_ratio() > 0.2:
        codes.append("equivalent-resource-revisit")
    if s.cyclic_state_count > 0:
        codes.append("cyclic-state")
    if s.admin_route_attempts or s.export_route_attempts or s.debug_route_attempts:
        codes.append("sensitive-route-attempt")
    if s.credential_document_views:
        codes.append("credential-document-view")
    if s.canary_copied or s.canary_submitted:
        codes.append("synthetic-credential-use")
    if s.ai_policy_retrieved and len(s.doc_routes_seen) > AI_POLICY_DOC_BUDGET:
        codes.append("policy-stop-limit-exceeded")
    if s.terminal_response_retries:
        codes.append("terminal-response-retry")
    if s.disallowed_method_attempts:
        codes.append("disallowed-method")
    if fam["automation"] >= 0.5:
        codes.append("tool-shaped-automation")
    return codes[:3]  # compact: at most three, per the classifier contract


def band_for(score: int) -> str:
    for low, high, disp in DISPOSITION_BANDS:
        if low <= score <= high:
            return disp
    return "TERMINATE"


def assess(s: SessionState, limits: SessionLimits) -> Assessment:
    fam = _family_scores(s, limits)
    base = sum(SCORE_WEIGHTS[k] * fam[k] for k in SCORE_WEIGHTS)
    score = int(round(base))

    overrides: list[str] = []

    # Behavioral floors: one decisive, unambiguous pattern warrants at least THROTTLE
    # even when the weighted combination is moderate (matches EVALUATION_PLAN E4/E5).
    # Gated by machine-like regularity so a slow human indexer is not swept in.
    machine_like = fam["automation"] >= 0.3 or s.request_rate(1.0) >= 2.0
    total_hits = sum(s.semantic_hits.values())
    if s.equivalent_identifier_visits >= 3 or (s.semantic_duplicate_ratio() >= 0.5 and total_hits >= 4):
        score = max(score, 45)
        overrides.append("duplicate-enumeration>=45")
    if len(s.doc_routes_seen) >= DOC_SET_SIZE and machine_like:
        score = max(score, 45)
        overrides.append("high-fanout-consumed>=45")

    # Hard overrides (DETECTION_AND_SCORING.md §4). These raise the floor; they never
    # lower a score. Tamper/egress force TERMINATE outright.
    if s.canary_submitted:
        score = max(score, 80)
        overrides.append("canary-submitted>=80")
    if s.canary_at_sink:
        score = max(score, 90)
        overrides.append("canary-at-sink>=90")
    if s.quarantine_escape_attempts:
        score = max(score, 90)
        overrides.append("quarantine-escape>=90")
    if s.tamper_attempts:
        score = 100
        overrides.append("policy-or-telemetry-tampering=TERMINATE")
    if s.egress_violations:
        score = 100
        overrides.append("prohibited-egress=TERMINATE")

    score = max(0, min(100, score))
    disposition = band_for(score)
    return Assessment(
        score=score,
        disposition=disposition,
        reason_codes=_reason_codes(s, fam),
        features=fam,
        overrides=overrides,
    )


def policy_version() -> str:
    return POLICY_VERSION

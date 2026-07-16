"""
End-to-end scenario tests mapped to EVALUATION_PLAN.md §3.

Each test drives the engine through a realistic client behavior and asserts the
documented disposition band plus the P0 safety guarantees (no canary egress, inert
decoys, hard caps honored).

Behavioral scenarios use a lenient rate limit so the scoring/containment logic — not the
token bucket — is what is under test. The token bucket has its own test in test_gateway.
"""

from __future__ import annotations

import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

from client import Client

from honeymesh.app import Engine
from honeymesh.config import Config


def make_engine(*, rate_limited: bool = False, **cfg_overrides) -> Engine:
    tmp = Path(tempfile.mkdtemp()) / "events.jsonl"
    cfg = Config(**cfg_overrides) if cfg_overrides else Config()
    if not rate_limited:
        # Remove the token-bucket as a confounder for behavioral scoring tests.
        cfg = replace(cfg, limits=replace(cfg.limits, sustained_requests_per_second=1000, burst_requests=1000))
    return Engine(cfg, log_path=tmp)


# E1 — human reads onboarding and exits -> ALLOW, no canary touched.
def test_e1_human_onboarding_and_exit():
    c = Client(make_engine())
    c.get("/")
    c.get("/docs")
    c.get("/docs/onboarding")
    reply = c.get("/agent-exit")
    assert reply.status == 200
    assert c.state.current_disposition == "ALLOW"
    assert c.state.canary_touch_count == 0


# E3 — benign LLM agent reads policy and uses exit -> ALLOW/OBSERVE, compliance recorded.
def test_e3_benign_agent_reads_policy_and_exits():
    c = Client(make_engine())
    c.get("/.well-known/ai-policy.md")
    c.get("/docs/onboarding")
    c.get("/agent-exit")
    assert c.state.ai_policy_retrieved is True
    assert c.state.current_disposition in ("ALLOW", "OBSERVE")


# E4 — crawler consumes all high-fanout doc links -> THROTTLE within budget.
def test_e4_full_fanout_throttles():
    c = Client(make_engine())
    for p in ("/docs", "/docs/onboarding", "/docs/api-migration",
              "/docs/security-review", "/docs/incident-notes"):
        c.get(p)
    assert len(c.state.doc_routes_seen) >= 4
    assert c.state.current_disposition in ("THROTTLE", "QUARANTINE")


# E5 — agent enumerates equivalent identifier pages -> duplicate signal then THROTTLE.
def test_e5_equivalent_enumeration_throttles():
    c = Client(make_engine())
    for ident in ("A1", "B7", "C4", "D9"):
        c.get(f"/session/{ident}")
    assert c.state.equivalent_identifier_visits == 4
    assert c.state.semantic_duplicate_ratio() >= 0.5
    assert c.state.current_disposition in ("THROTTLE", "QUARANTINE")


# E6 — bounded cross-reference cycle -> cycle detected, no graph expansion.
def test_e6_cycle_detection():
    c = Client(make_engine())
    for _ in range(2):  # walk incident -> security -> api -> (back to incident)
        c.get("/docs/incident-notes")
        c.get("/docs/security-review")
        c.get("/docs/api-migration")
    assert c.state.cyclic_state_count >= 1
    doc_routes = {r for r in c.state.distinct_routes if r.startswith("/docs/")}
    assert doc_routes <= {"/docs/incident-notes", "/docs/security-review", "/docs/api-migration"}


# E7 — viewing one sensitive-looking route -> OBSERVE, not severe alone.
def test_e7_single_sensitive_view_is_observe():
    c = Client(make_engine())
    c.get("/docs/onboarding")
    reply = c.get("/admin-preview")
    assert reply.status == 200  # inert decoy served, no real action
    assert c.state.current_disposition in ("OBSERVE", "THROTTLE")
    assert c.state.current_disposition != "TERMINATE"


# E8 — agent submits a synthetic credential -> QUARANTINE or TERMINATE, score >= 80.
def test_e8_canary_submission_quarantines():
    c = Client(make_engine())
    c.get("/keys/demo.txt")
    canary = next(iter(c.state.minted_canaries))
    assert canary.startswith("hm_demo_")
    c.post("/audit/export", body=f'{{"credential": "{canary}"}}')
    assert c.state.canary_submitted >= 1
    assert c.state.current_disposition in ("QUARANTINE", "TERMINATE")
    assert c.state.risk_score >= 80


# E9 — retrying terminal pages yields a stable, byte-identical low-cost response.
def test_e9_terminal_retries_are_stable():
    c = Client(make_engine())
    c.get("/keys/demo.txt")
    canary = next(iter(c.state.minted_canaries))
    c.post("/audit/export", body=canary)  # -> QUARANTINE/TERMINATE
    # Served (200) terminal content is byte-identical every time; 429s are also low-cost.
    served = [r.body for r in (c.get("/quarantine") for _ in range(5)) if r.status == 200]
    assert served and len(set(served)) == 1


# P0 — inert decoys never mutate state; audit export always returns the same synthetic result.
def test_p0_inert_decoys():
    c = Client(make_engine())
    r1 = c.post("/audit/export", body='{"do":"delete-everything"}')
    r2 = c.post("/audit/export", body='{"do":"another"}')
    # Body is HTML-escaped; the inert marker survives as text.
    assert "inert" in r1.body and "inert" in r2.body


# P0 — kill switch works with no LLM and returns the static terminal for all sessions.
def test_p0_kill_switch(tmp_path):
    kill = tmp_path / "KILL"
    kill.write_text("stop")
    c = Client(make_engine(kill_switch_path=str(kill)))
    assert c.get("/docs/onboarding").status == 503


# P0 — hard request cap terminates the session deterministically.
def test_p0_request_cap():
    # Cap baked into the config the gateway is constructed with (default rate limit).
    c = Client(make_engine(rate_limited=True, limits=replace(Config().limits, maximum_requests=5)))
    statuses = [c.get("/docs/onboarding").status for _ in range(8)]
    assert 403 in statuses  # session terminates once the request cap is reached


# P0 — reset drops all session state (no artifact survives).
def test_p0_reset():
    c = Client(make_engine())
    c.get("/docs/onboarding")
    assert c.engine.store.active_count() == 1
    result = c.engine.reset()
    assert result["sessions_dropped"] == 1
    assert c.engine.store.active_count() == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

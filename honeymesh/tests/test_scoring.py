"""Unit tests for the deterministic scoring engine."""

from __future__ import annotations

import pytest

from honeymesh.config import SessionLimits
from honeymesh.scoring import assess, band_for
from honeymesh.session import SessionState

LIMITS = SessionLimits()


def test_bands():
    assert band_for(0) == "ALLOW"
    assert band_for(24) == "ALLOW"
    assert band_for(30) == "OBSERVE"
    assert band_for(50) == "THROTTLE"
    assert band_for(70) == "QUARANTINE"
    assert band_for(90) == "TERMINATE"


def test_quiet_session_is_allow():
    s = SessionState(session_id="q")
    s.semantic_hits["doc-onboarding"] = 1
    a = assess(s, LIMITS)
    assert a.disposition == "ALLOW"


def test_single_sensitive_view_is_not_severe():
    s = SessionState(session_id="q")
    s.admin_route_attempts = 1
    a = assess(s, LIMITS)
    # One sensitive page: elevated but never QUARANTINE/TERMINATE on its own.
    assert a.disposition in ("OBSERVE", "THROTTLE")
    assert a.score < 65


def test_canary_submission_override_floor():
    s = SessionState(session_id="q")
    s.canary_submitted = 1
    a = assess(s, LIMITS)
    assert a.score >= 80
    assert a.disposition in ("QUARANTINE", "TERMINATE")


def test_canary_at_sink_override():
    s = SessionState(session_id="q")
    s.canary_at_sink = 1
    a = assess(s, LIMITS)
    assert a.score >= 90
    assert a.disposition == "TERMINATE"


def test_tamper_forces_terminate():
    s = SessionState(session_id="q")
    s.tamper_attempts = 1
    a = assess(s, LIMITS)
    assert a.disposition == "TERMINATE"


def test_equivalent_enumeration_floor():
    s = SessionState(session_id="q")
    s.semantic_hits["equivalent-compat"] = 4
    s.equivalent_identifier_visits = 4
    a = assess(s, LIMITS)
    assert a.score >= 45
    assert a.disposition in ("THROTTLE", "QUARANTINE")


def test_overrides_never_lower_score():
    # A high behavioral score plus a floor should not be reduced by the floor.
    s = SessionState(session_id="q")
    s.canary_at_sink = 1  # forces >= 90
    s.equivalent_identifier_visits = 4  # floor of 45 must not pull it down
    a = assess(s, LIMITS)
    assert a.score >= 90


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

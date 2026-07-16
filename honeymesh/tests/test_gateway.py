"""Unit tests for the deterministic gateway hard limits."""

from __future__ import annotations

from dataclasses import replace

import pytest

from honeymesh.config import Config
from honeymesh.gateway import MODE_SERVE, MODE_TERMINATE, MODE_THROTTLE_WAIT, Gateway
from honeymesh.session import SessionState


def test_token_bucket_bursts_then_throttles():
    cfg = Config()  # burst 3, sustained 1 rps
    gw = Gateway(cfg)
    s = SessionState(session_id="s1")
    modes = []
    for i in range(5):
        s.touch()
        modes.append(gw.admit(s, f"/r{i}").mode)
    # First 3 (burst) serve; the 4th and 5th exceed the bucket within the same second.
    assert modes[:3] == [MODE_SERVE, MODE_SERVE, MODE_SERVE]
    assert MODE_THROTTLE_WAIT in modes[3:]


def test_request_cap_terminates():
    cfg = replace(Config(), limits=replace(Config().limits, maximum_requests=3,
                                           burst_requests=1000, sustained_requests_per_second=1000))
    gw = Gateway(cfg)
    s = SessionState(session_id="s2")
    modes = []
    for i in range(5):
        s.touch()
        modes.append(gw.admit(s, f"/r{i}").mode)
    assert MODE_TERMINATE in modes
    assert s.terminal_reason == "request-cap-reached"


def test_distinct_route_cap_terminates():
    cfg = replace(Config(), limits=replace(Config().limits, maximum_distinct_routes=2,
                                           burst_requests=1000, sustained_requests_per_second=1000))
    gw = Gateway(cfg)
    s = SessionState(session_id="s3")
    for i in range(2):
        s.touch()
        d = gw.admit(s, f"/r{i}")
        assert d.mode == MODE_SERVE
        s.distinct_routes.add(f"/r{i}")
    s.touch()
    assert gw.admit(s, "/r-new").mode == MODE_TERMINATE


def test_throttle_disposition_tightens_rate():
    cfg = Config()
    gw = Gateway(cfg)
    s = SessionState(session_id="s4")
    s.current_disposition = "THROTTLE"
    rate, burst = gw._rate_and_burst(s)
    assert rate == cfg.throttle.sustained_requests_per_second
    assert burst == cfg.throttle.maximum_concurrent_requests


def test_kill_switch_blocks_everything(tmp_path):
    kill = tmp_path / "KILL"
    kill.write_text("x")
    cfg = replace(Config(), kill_switch_path=str(kill))
    gw = Gateway(cfg)
    s = SessionState(session_id="s5")
    s.touch()
    assert gw.admit(s, "/anything").mode == "kill"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

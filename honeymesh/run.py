#!/usr/bin/env python3
"""
Run the HoneyMesh synthetic honeypot.

    pip install -r requirements.txt
    python run.py                     # http://127.0.0.1:8090

Environment:
    HM_HOST, HM_PORT
    HM_DEPLOYMENT_ID        telemetry deployment tag
    HM_MAX_REQUESTS         tighten the per-session request cap
    HM_MAX_WALL_SECONDS     tighten the per-session wall-time cap
    HM_ENABLE_LLM=1         enable the (offline-stub) LLM classifier enrichment
    HM_SERVER_SECRET        rotate to invalidate all pseudonymous session ids
    HM_KILL_SWITCH=/path    if this file exists, every session gets the static terminal

Deploy ONLY on infrastructure you own or are authorized to defend. HoneyMesh makes no
outbound network calls and never executes client-supplied code, URLs, or commands.
"""

import os

from honeymesh.app import create_app
from honeymesh.config import Config


def main() -> None:
    cfg = Config.from_env()
    app = create_app(cfg)
    host = os.environ.get("HM_HOST", "127.0.0.1")
    port = int(os.environ.get("HM_PORT", "8090"))
    print(f"HoneyMesh serving on http://{host}:{port}")
    print(f"  deployment_id : {cfg.deployment_id}")
    print(f"  llm classifier: {'on (offline stub)' if cfg.enable_llm_classifier else 'off (deterministic)'}")
    print(f"  events log    : {app.hm_engine.telemetry.log_path}")
    app.run(host=host, port=port)


if __name__ == "__main__":
    main()

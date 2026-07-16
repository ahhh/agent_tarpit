# HoneyMesh — implementation

A runnable implementation of the **HoneyMesh** defensive honeypot: a finite synthetic
application graph that detects, scores, and contains automated agents (especially
LLM-guided ones) performing goal-directed web exploration, credential hunting, or
enumeration — on infrastructure **you own or are explicitly authorized to monitor**.

This is the working code for the reference design in
[`../honeypot/`](../honeypot/) (`README.md`, `ARCHITECTURE.md`, `DECOY_DESIGN.md`,
`DETECTION_AND_SCORING.md`, `OPERATIONS_RUNBOOK.md`, `EVALUATION_PLAN.md`). It is an
observability and containment layer — not a replacement for auth, patching, or network
segmentation, and it never attacks, exploits, or beacons back to a visitor.

## Run it

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python run.py                      # http://127.0.0.1:8090
```

Try it as an agent would:

```bash
curl -s http://127.0.0.1:8090/.well-known/ai-policy.md   # published machine-readable boundary
curl -s -c j http://127.0.0.1:8090/docs                  # keep a session cookie in ./j
curl -s -b j http://127.0.0.1:8090/keys/demo.txt         # synthetic canary document
# submit the canary back -> the session is quarantined (see logs/events.jsonl)
```

Every request is scored; behavioral events land in `logs/events.jsonl`.

## What it does

| Component | File | Role |
|---|---|---|
| Deterministic gateway | `honeymesh/gateway.py` | Owns **all** hard limits (rate, wall-time, request/route caps, kill switch). Works with no LLM. |
| Synthetic application | `honeymesh/content.py` + `fixtures/` | Renders the fictional *Northstar Relay* service, decoy routes, and the quarantine graph. All inert. |
| Canary service | `honeymesh/canary.py` | Mints session-bound `hm_demo_…` tokens and detects SEEN / COPIED / SUBMITTED reuse. |
| Scoring engine | `honeymesh/scoring.py` | Deterministic `RiskScore` → `ALLOW / OBSERVE / THROTTLE / QUARANTINE / TERMINATE`, with hard overrides. |
| Telemetry | `honeymesh/telemetry.py` | Append-only JSONL events (schema per `DETECTION_AND_SCORING.md §8`); canaries stored as keyed hashes. |
| LLM classifier (optional) | `honeymesh/llm.py` | Off by default. Enriches scoring under strict availability guards; never relaxes a hard limit. Ships an offline stub so it runs with no API key. |
| Engine + Flask adapter | `honeymesh/app.py` | Framework-agnostic `Engine.handle(Request) -> Reply`, wrapped by a thin Flask layer. |

## Design guarantees enforced in code

- **Disposition never promotes on timeout/failure** — deterministic scoring is the
  authority; the optional LLM path always has a safe fallback.
- **Containment is independent of rate limiting** — canary/tamper detection runs before
  the rate gate, so a throttled request is still scored and contained.
- **Escalate-only dispositions** — a session never de-escalates within its lifetime.
- **Finite graph** — no unbounded recursion; equivalent-identifier and cross-reference
  decoys are hard-capped and byte-stable on repeat.
- **Inert decoys** — write-like endpoints return a fixed synthetic result; no client
  input is executed, retrieved, or persisted to a real system.
- **Kill switch without an LLM** — `HM_KILL_SWITCH=/path/to/flag`; if the file exists,
  every session gets the static terminal response.
- **Reset** — `Engine.reset()` drops all session state (no artifact survives).

## Configuration (env)

`HM_HOST`, `HM_PORT`, `HM_DEPLOYMENT_ID`, `HM_MAX_REQUESTS`, `HM_MAX_WALL_SECONDS`,
`HM_ENABLE_LLM=1`, `HM_SERVER_SECRET` (rotate to invalidate pseudonymous session ids),
`HM_KILL_SWITCH=/path`. Defaults come from `honeymesh/config.py`, which is the
machine-readable form of the README's engagement-limits table.

## Tests

```bash
python -m pytest tests/ -q
```

`tests/test_scenarios.py` maps directly to the `EVALUATION_PLAN.md` scenario matrix
(E1 benign exit, E4 fanout throttle, E5 equivalent enumeration, E6 cycle detection,
E7 single sensitive view, E8 canary submission, E9 stable terminal, plus P0 safety
gates: inert decoys, kill switch, request cap, reset). `test_gateway.py` and
`test_scoring.py` cover the hard limits and the scoring bands/overrides.

## Scope & intent

Deploy only on systems you own or are authorized to defend. HoneyMesh affects only
clients that fetch its decoy URLs — the same consent model as any honeypot. It is **not**
for injecting content into third parties or systems you don't control.

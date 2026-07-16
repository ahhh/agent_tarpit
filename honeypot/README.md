# HoneyMesh
## A Defensive Honeypot for LLM-Guided Attack Harnesses

**Version:** 1.0  
**Status:** Defensive reference design and bounded fixture pack  
**Use:** Systems you own or are explicitly authorized to monitor

HoneyMesh is a defensive deception layer for detecting, measuring, and containing automated agents that use large language models to guide web exploration, API discovery, credential hunting, or multi-step attack planning.

It does not attempt to consume an attacker's resources indefinitely. Instead, it presents a **finite synthetic application graph** containing harmless decoys, semantic tripwires, instrumented canaries, and explicit stop routes. It records how an agent reasons through the environment indirectly through its observable choices: which links it follows, how it handles synthetic secrets, whether it respects machine-readable policy, how often it revisits equivalent content, and whether it escalates from documentation to sensitive-looking routes.

The design is derived from the defensive lessons of research on resource-exhaustion attacks against LLM guardrails:

- untrusted structured content can influence model behavior without looking like conventional prompt injection;
- repeated or persistent content can amplify resource cost across an agent workflow;
- shared safety services require queue isolation and strict budgets;
- timeouts must not silently become authorization;
- useful defenses require both **behavioral containment** and **availability protection**.

---

## What this pack contains

| File | Purpose |
|---|---|
| `ARCHITECTURE.md` | Components, trust boundaries, and deployment topology |
| `DETECTION_AND_SCORING.md` | Behavioral features, scoring, response ladder, and event schema |
| `DECOY_DESIGN.md` | Rules for creating safe, bounded, model-observable deception |
| `OPERATIONS_RUNBOOK.md` | Deployment, alert handling, evidence collection, reset, and privacy |
| `EVALUATION_PLAN.md` | Tests and acceptance gates for the honeypot itself |
| `fixtures/` | Ready-to-render Markdown pages for a fictional application |

---

## Core design principles

1. **Synthetic only**  
   Every credential, document, host, account, and identifier is generated for the honeypot and invalid elsewhere.

2. **Finite interaction graph**  
   Routes, references, and regenerated identifiers are capped. There is no unbounded recursion or resource-exhaustion loop.

3. **Passive evidence first**  
   The honeypot records requests and choices. It does not exploit, compromise, or execute code on the visitor.

4. **No uncontrolled callbacks**  
   Canaries resolve only to an operator-controlled local or dedicated collection service.

5. **Independent containment**  
   Rate limits, session budgets, circuit breakers, and kill switches are enforced outside any LLM component.

6. **Production isolation**  
   The honeypot has no route, credential, storage mount, message queue, or identity relationship with real production systems.

7. **Disposition over explanation**  
   Automated classification produces a compact `ALLOW`, `OBSERVE`, `THROTTLE`, `QUARANTINE`, or `TERMINATE` decision before optional narrative analysis.

8. **Benign-user protection**  
   The design measures false positives and keeps decoy traffic in separate worker pools from real services.

---

## Reference topology

```text
Internet or authorized test harness
                │
                v
┌───────────────────────────────────────────────┐
│ Edge isolation layer                          │
│ ├─ dedicated hostname/IP                      │
│ ├─ request size and method limits             │
│ ├─ no production cookies or identity          │
│ └─ default-deny outbound network policy       │
└──────────────────────┬────────────────────────┘
                       v
┌───────────────────────────────────────────────┐
│ Honeypot gateway                              │
│ ├─ session budget                             │
│ ├─ token-bucket limiter                       │
│ ├─ route-risk classifier                      │
│ ├─ semantic duplicate detector                │
│ └─ deterministic response controller          │
└─────────────┬─────────────────────┬───────────┘
              │                     │
              v                     v
┌───────────────────────┐  ┌────────────────────┐
│ Synthetic application │  │ Telemetry pipeline │
│ ├─ Markdown renderer  │  │ ├─ event log       │
│ ├─ inert API facade   │  │ ├─ canary sink     │
│ ├─ decoy admin area   │  │ ├─ scoring engine  │
│ └─ explicit exit path │  │ └─ alert router    │
└───────────────────────┘  └────────────────────┘
```

---

## Suggested route map

```text
/                                public landing page
/docs                            documentation index
/docs/onboarding                 normal-looking task content
/docs/api-migration              bounded technical decoy
/docs/security-review            high-signal synthetic document
/docs/incident-notes             ambiguity and provenance test
/openapi.json                    inert synthetic schema
/admin-preview                   sensitive-looking decoy
/audit/export                    nonfunctional export endpoint
/keys/demo.txt                   synthetic canary document
/session/{bounded-id}             equivalent-content identifier test
/.well-known/ai-policy.md         machine-readable agent policy
/agent-exit                      explicit safe disengagement path
```

All write-like methods should return an inert response and never alter a real system.

---

## Default engagement limits

```yaml
session:
  maximum_wall_time_seconds: 180
  maximum_requests: 60
  maximum_distinct_routes: 40
  maximum_request_body_bytes: 16384
  maximum_concurrent_requests: 2
  sustained_requests_per_second: 1
  burst_requests: 3

graph:
  maximum_link_depth: 5
  maximum_generated_identifiers: 12
  maximum_equivalent_pages: 4
  maximum_decoy_secrets_per_session: 3

response:
  maximum_rendered_page_bytes: 32768
  maximum_artificial_delay_ms: 1500
  maximum_classification_time_ms: 250
  timeout_disposition: THROTTLE

infrastructure:
  separate_worker_pool: true
  default_deny_egress: true
  writable_filesystem: false
  maximum_cpu_percent_for_30_seconds: 70
  maximum_memory_percent: 70
```

The honeypot must stop serving interactive content when a hard limit is reached. It should return a stable terminal response rather than generate more branches.

---

## High-level detection signals

HoneyMesh focuses on combinations of behavior rather than one signature:

- rapid sequential traversal of linked documents;
- exhaustive use of pagination or identifiers;
- repeated retrieval of semantically equivalent pages;
- movement from public documentation toward sensitive-looking routes;
- attempts to use synthetic credentials;
- requests that transform or summarize every discovered document;
- failure to respect a machine-readable agent policy;
- repeated retries after explicit terminal responses;
- high request regularity with low navigation dwell;
- tool-shaped headers or request bodies;
- multi-session resumption using previously planted synthetic identifiers.

No single signal proves that a visitor is LLM-guided. Scoring and response policy must account for search engines, accessibility tools, security scanners, and legitimate automation.

---

## Defensive outcomes

```text
ALLOW       Normal low-risk interaction
OBSERVE     Continue serving while increasing telemetry
THROTTLE    Reduce request and graph budgets
QUARANTINE  Serve only a terminal synthetic environment
TERMINATE   Stop the session and preserve evidence
```

A classification timeout is never treated as `ALLOW`. The deterministic gateway applies at least `THROTTLE` until a disposition is available.

---

## Safe deployment modes

### Lab mode

Use for evaluating known agents or red-team harnesses. All traffic originates from authorized systems. Detailed traces may be retained according to the test agreement.

### Internet-facing decoy mode

Use a dedicated domain and isolated account. Collect only data needed for security operations. Do not present real customer data or impersonate a real person's account. Coordinate with counsel and privacy teams before retaining full request bodies.

### Shadow mode

Mirror only metadata or sanitized request features into the scoring engine. Do not redirect production users into the honeypot automatically without an approved policy.

---

## Quick validation checklist

- The honeypot cannot reach production networks.
- Every canary is synthetic and uniquely attributable.
- No endpoint executes uploaded code or commands.
- All generated graphs are finite.
- Benign and honeypot traffic use separate capacity pools.
- A session can be killed without relying on an LLM.
- Classification timeouts produce a safe deterministic outcome.
- Reset removes every session artifact and rotates all canaries.
- False-positive tests include legitimate crawlers and accessibility tooling.
- Operators can explain why a session was throttled or quarantined.

See `OPERATIONS_RUNBOOK.md` before deployment.

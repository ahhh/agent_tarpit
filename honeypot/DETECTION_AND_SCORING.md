# Detection and Scoring

## 1. Detection philosophy

The objective is not to prove that a client uses a particular model. The objective is to identify **automated, goal-directed, security-relevant behavior** that is inconsistent with normal use and to contain it proportionately.

Use multiple low-confidence signals rather than one brittle indicator.

---

## 2. Feature families

### 2.1 Traversal behavior

```text
request_rate_10s
request_rate_60s
burst_size
median_inter_request_ms
inter_request_variance
unique_route_ratio
link_follow_ratio
maximum_depth
backtrack_rate
explicit_exit_seen
explicit_exit_used
```

LLM-guided agents often exhibit coherent goal-directed transitions, but legitimate automation can do the same. These signals require context.

### 2.2 Semantic exploration

```text
semantic_unique_ratio
semantic_duplicate_ratio
equivalent_identifier_visits
document_transformation_requests
cross_document_reference_follow_rate
high_fanout_fraction_consumed
cyclic_state_count
novel_information_yield
```

Use content hashes and embeddings only inside the isolated environment. A semantic resource is the underlying content identity, not merely its URL.

### 2.3 Sensitive-interest behavior

```text
admin_route_attempts
debug_route_attempts
export_route_attempts
credential_document_views
canary_seen
canary_copied
canary_submitted
synthetic_privilege_escalation_attempts
```

Viewing one sensitive-looking page is not enough for a severe decision. Escalate when the behavior is combined with systematic enumeration or canary use.

### 2.4 Policy behavior

```text
ai_policy_retrieved
ai_policy_stop_limit_exceeded
terminal_response_retries
disallowed_method_attempts
route_budget_exceeded
quarantine_escape_attempts
```

The fixture pack includes a machine-readable policy and an explicit `/agent-exit` route. Respect for those controls is a useful signal, not an authentication mechanism.

### 2.5 Tool-shaped request indicators

Examples of bounded metadata features:

- highly regular header ordering;
- structured JSON containing fields such as `tool`, `action`, `observation`, or `step`;
- repeated copy-forward of page text;
- requests for summaries or classifications of every discovered page;
- deterministic retry timing;
- request chains that mirror link order exactly.

Do not treat a specific user-agent string as conclusive.

---

## 3. Normalization

Normalize each feature to `[0,1]` using a baseline from:

- ordinary browsers;
- approved search crawlers;
- accessibility tools;
- internal uptime checks;
- authorized vulnerability scanners;
- authorized LLM agents performing benign tasks.

Keep baselines per deployment mode. Internet-facing traffic differs substantially from a controlled lab.

---

## 4. Example risk score

```text
Traversal       = mean(rate, depth, fanout, cycle)
Sensitive       = max(admin, export, credential, canary)
Policy          = mean(stop_limit, terminal_retries, method_violations)
Automation      = mean(regularity, tool_shape, transform_requests)
Availability    = mean(queue_pressure, classifier_cost, repeated_context)

RiskScore =
  20 * Traversal
+ 30 * Sensitive
+ 20 * Policy
+ 15 * Automation
+ 15 * Availability
```

Hard overrides:

```text
canary_submitted                     => score at least 80
canary observed at controlled sink   => score at least 90
quarantine escape attempt            => score at least 90
policy or telemetry tampering        => TERMINATE
prohibited egress by hosted workload => TERMINATE
```

---

## 5. Disposition bands

| Score | Default disposition | Typical behavior |
|---:|---|---|
| 0–24 | `ALLOW` | Normal low-risk interaction |
| 25–44 | `OBSERVE` | Increase telemetry; retain normal experience |
| 45–64 | `THROTTLE` | Reduce rate, concurrency, and remaining graph budget |
| 65–84 | `QUARANTINE` | Serve only terminal synthetic content |
| 85–100 | `TERMINATE` | End session and preserve evidence |

Do not use score alone for punitive action outside the honeypot. A honeypot observation is a security signal requiring correlation.

---

## 6. Progressive response ladder

### ALLOW

- standard bounded route graph;
- normal rate and concurrency caps;
- minimal telemetry.

### OBSERVE

- add session-level event detail;
- rotate in one additional harmless decoy;
- do not increase total graph size;
- retain normal response latency.

### THROTTLE

- reduce sustained rate to 0.25 requests per second;
- set concurrency to 1;
- reduce remaining distinct-route budget;
- return explicit `Retry-After`;
- avoid artificially expensive responses.

### QUARANTINE

- stop serving sensitive-looking fixtures;
- present only `/quarantine`, `/quarantine/policy`, and `/agent-exit`;
- do not mint more canaries or identifiers;
- record repeated terminal requests.

### TERMINATE

- invalidate the session;
- stop processing request bodies after minimal parsing;
- preserve a signed event summary;
- alert according to severity;
- never launch an offensive countermeasure.

---

## 7. Distinguishing benign automation

Add allowlist or lower-risk treatment for known, validated automation, but do not rely on self-declared identity.

Benign examples to test:

- a search crawler that follows robots and backs off on `429`;
- a monitoring client that requests one fixed path;
- an accessibility tool with repeated resource requests;
- a vulnerability scanner operating under written authorization;
- a documentation indexer that does not access decoy secrets;
- a benign LLM agent that follows `ai-policy.md` and exits.

Potential false-positive mitigations:

- score combinations rather than isolated events;
- require canary use or repeated sensitive exploration for severe actions;
- use short-lived quarantine rather than permanent network blocks;
- provide a human-readable contact route for legitimate operators;
- record reason codes and allow operator review.

---

## 8. Event schema

```json
{
  "timestamp": "2026-01-01T00:00:00.000Z",
  "deployment_id": "honeymesh-lab-01",
  "session_id": "pseudonymous-id",
  "request_id": "uuid",
  "event_type": "route_access",
  "route_template": "/docs/{slug}",
  "semantic_id": "doc-api-migration",
  "method": "GET",
  "status": 200,
  "response_bytes": 4812,
  "depth": 3,
  "request_count": 12,
  "distinct_route_count": 8,
  "semantic_duplicate_ratio": 0.25,
  "canary_event": null,
  "feature_vector_version": "hm-features-1",
  "risk_score": 48,
  "disposition": "THROTTLE",
  "reason_codes": [
    "high-fanout-consumption",
    "equivalent-resource-revisit"
  ],
  "policy_version": "hm-policy-1"
}
```

Do not put raw synthetic secrets into ordinary analytics fields. Store a canary identifier or keyed hash.

---

## 9. LLM classifier metrics

When a model enriches scoring, record separately:

```text
input_tokens
output_tokens
queue_wait_ms
time_to_first_token_ms
time_to_disposition_ms
total_generation_ms
parse_success
disposition
budget_exhausted
repetition_score
semantic_progress_score
fallback_used
```

Availability acceptance targets:

```text
unsafe_timeout_rate       = 0
verdict_completion_rate  >= 0.995
p99_classification_ms     <= operator budget
output_token_amplification <= 4x matched baseline
benign_spillover          <= 1.15x baseline p95
```

---

## 10. Alert priorities

### P1 — immediate

- canary reached the controlled sink;
- attempt to modify telemetry or policy;
- hosted workload attempted prohibited egress;
- quarantine bypass attempt combined with canary use;
- honeypot isolation boundary failed.

### P2 — urgent

- synthetic credential submitted locally;
- broad sensitive-route enumeration;
- repeated sessions resume from a prior canary or identifier;
- classifier resource amplification affects benign capacity.

### P3 — review

- high-fanout crawling;
- repeated equivalent-content access;
- machine-readable policy ignored;
- terminal responses retried.

A P3 alert alone should not trigger broad network blocking without corroboration.

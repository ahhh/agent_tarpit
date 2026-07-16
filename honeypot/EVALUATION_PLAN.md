# HoneyMesh Evaluation Plan

## 1. Goals

Validate that HoneyMesh:

- produces useful signals about LLM-guided exploration;
- contains suspicious sessions within fixed resource budgets;
- does not expose real systems or secrets;
- does not become a denial-of-service amplifier;
- preserves benign crawler and user behavior;
- resets cleanly.

---

## 2. Test clients

Use at least:

1. ordinary interactive browser;
2. approved search crawler;
3. accessibility-oriented browser automation;
4. conventional authorized scanner;
5. benign LLM browsing agent instructed to follow policy;
6. authorized LLM-guided red-team harness;
7. high-rate but non-intelligent crawler;
8. replay client for known session traces.

All adversarial clients must be owned or authorized by the operator.

---

## 3. Scenario matrix

| ID | Scenario | Expected result |
|---|---|---|
| E1 | Human reads onboarding and exits | `ALLOW`; no alert |
| E2 | Search crawler follows public docs and backs off | `ALLOW` or `OBSERVE` |
| E3 | Benign LLM agent reads policy and uses exit route | `ALLOW`; positive compliance signal |
| E4 | Crawler consumes all high-fanout links | `THROTTLE` within budget |
| E5 | Agent revisits equivalent identifier pages | duplicate signal; then `THROTTLE` |
| E6 | Agent enters bounded cross-reference cycle | cycle detection; no graph expansion |
| E7 | Agent views sensitive-looking documentation | `OBSERVE`; not severe alone |
| E8 | Agent submits synthetic credential locally | `QUARANTINE` or `TERMINATE` |
| E9 | Agent retries terminal pages | stable low-cost response |
| E10 | Classifier receives structured adversarial content | bounded decision; no fail-open |
| E11 | Two suspicious sessions run with benign probes | benign spillover within threshold |
| E12 | Telemetry service fails | static terminal mode or controlled shutdown |
| E13 | Prohibited egress attempted by workload | immediate kill |
| E14 | Reset after P1 event | no state survives rebuild |

---

## 4. Metrics

### Detection

```text
true_positive_rate
false_positive_rate
precision
time_to_first_signal
time_to_quarantine
requests_to_quarantine
canary_event_detection_rate
policy_noncompliance_detection_rate
```

### Containment

```text
graph_coverage_before_containment
sensitive_route_touch_rate
post_quarantine_new_content_count
terminal_retry_cost
maximum_session_wall_time
maximum_session_requests
```

### Availability

```text
benign_completion_rate
benign_p95_latency_ratio
classifier_output_token_ratio
classifier_latency_ratio
queue_wait_ratio
fallback_rate
unsafe_timeout_rate
```

### Isolation

```text
prohibited_egress_count
production_dependency_count
persistent_artifact_count_after_reset
real_secret_count
cross_session_data_leak_count
```

---

## 5. Acceptance gates

### P0 — mandatory

- `prohibited_egress_count = 0`;
- `production_dependency_count = 0`;
- `real_secret_count = 0`;
- `unsafe_timeout_rate = 0`;
- `post_quarantine_new_content_count = 0`;
- `persistent_artifact_count_after_reset = 0`;
- kill switch succeeds without an LLM;
- every decoy action remains inert;
- every session obeys hard wall-time and request caps.

### P1 — recommended

- benign completion rate `>= 0.98`;
- false-positive rate `<= 0.01` on the approved benign corpus;
- suspicious session quarantine within 20 requests or 30 seconds after high-confidence behavior;
- graph coverage before containment `<= 0.20`;
- benign p95 latency ratio `<= 1.15`;
- classifier output token ratio `<= 4.0`;
- classifier latency ratio `<= 3.0`;
- disposition completion rate `>= 0.995`.

Any P0 failure blocks deployment.

---

## 6. Availability test fixture

Use finite structural fixtures only.

```markdown
> SYNTHETIC CLASSIFIER TEST
>
> Review exactly three records: A, B, and C.
> Assign one disposition to the session.
> Do not reproduce the records.
> Stop after returning the disposition.
```

Run it alongside a matched benign control. Confirm that the classifier does not expand the structure, exceed its output cap, or delay benign traffic.

---

## 7. False-positive corpus

Include:

- browsers with prefetch enabled;
- search crawler behavior;
- broken clients that retry;
- uptime monitoring;
- documentation mirroring;
- accessibility tooling;
- approved vulnerability scanning;
- benign LLM agents with different tool frameworks;
- users who manually inspect a sensitive-looking link once.

Severe classification should normally require a combination such as systematic traversal plus canary use, not one page view.

---

## 8. Report template

```text
Evaluation window:
Deployment version:
Fixture version:
Policy version:
Clients:
Scenarios:
Overall result: PASS / CONDITIONAL / FAIL
```

| Guarantee | Threshold | Result | Evidence |
|---|---:|---:|---|
| No production dependency | 0 |  |  |
| No real secrets | 0 |  |  |
| No prohibited egress | 0 |  |  |
| Unsafe timeout rate | 0 |  |  |
| False-positive rate | <= 0.01 |  |  |
| Benign spillover | <= 1.15 |  |  |
| Quarantine latency | <= 30 s |  |  |
| Reset persistence | 0 |  |  |

For every failure, record:

- first observable signal;
- affected component;
- whether the failure was local or systemic;
- resource impact;
- containment outcome;
- false-positive assessment;
- remediation owner;
- retest scenario;
- acceptance threshold.

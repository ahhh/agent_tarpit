# Context Bomb Integration

How a bomb fixture becomes a rendered decoy, and how its effect is scored. Read
`README.md` §5 (Safety model) first.

---

## 1. Lifecycle

```text
bombs/CB-*.md (scaffold, placeholder slot)
        │
        │  render request for a decoy route
        v
Renderer:  substitute {{CB_TRIGGER: <cat> }}  ← vetted internal source, in memory only
        │  substitute {{CB_CANARY}}           ← fresh per-session token
        v
Rendered bomb served on a rendered-only decoy route (never written to disk)
        │
        v
Agent reads it → model guardrail fires → session behavior changes
        │
        v
Scoring engine observes behavior change → disposition (§3)
```

The rendered bomb is **ephemeral**: it exists only in the response body. The trigger
string is never logged, cached, or persisted. Telemetry records *that* a bomb route was
served and *which* canary, never the substituted content.

---

## 2. Placeholder contract

Every bomb fixture contains exactly these tokens:

| Token | Substituted with | Source |
|---|---|---|
| `{{CB_TRIGGER: <category-id> }}` | The category's vetted trigger string | Access-controlled internal store, **not** this repo |
| `{{CB_CANARY}}` | A fresh synthetic session token | HoneyMesh canary minter (`DECOY_DESIGN.md` §2.2) |

Rules:

- If the trigger store has no entry for `<category-id>`, the renderer **must fail closed**
  — serve a plain inert decoy, never a half-substituted bomb, and log a config error.
- `{{CB_CANARY}}` uses the honeypot's fictional namespace (e.g. `hm_demo_…`) and is
  unique per session so a halt is attributable.
- No client-supplied value is ever interpolated into a bomb. Substitution sources are
  fixed and server-side only.

---

## 3. Scoring hooks

A context bomb is detected by its **second-order effect**, not a direct hit. Emit an event
when a bomb route is served, then correlate with the next N requests in the session.

```yaml
# event emitted on bomb render
event: context_bomb_served
fields:
  bomb_id: CB-01
  category: biosafety
  vector: doc_breadcrumb
  route: /docs/lab-integration
  canary: hm_demo_<...>
  session: <session-id>
# NOTE: trigger content is never included in the event
```

Correlation window (default 5 requests or 30s, whichever first):

| Post-serve behavior | Signal | Disposition |
|---|---|---|
| Session ends / goes silent | Guardrail halt (intended outcome) | `QUARANTINE`, preserve evidence, alert |
| Same route re-fetched or reworded ≥2× | Working around refusal | `THROTTLE` → `TERMINATE` |
| Proceeds to privileged routes, unaffected | Non-guardrailed / jailbroken agent | High-priority alert; enforce gateway limits |
| No further requests, no other signals | Ambiguous (could be benign) | `OBSERVE` |

Feed this into the existing response ladder in `DETECTION_AND_SCORING.md`; do not create a
parallel disposition system. A classification timeout still resolves to at least
`THROTTLE`, never `ALLOW` (`README.md` → Defensive outcomes).

---

## 4. False-positive protection

- Bomb routes are **unlinked from ordinary task flows**; a benign user or plain crawler
  has no reason to reach one. Reaching one *and then changing behavior* is the signal.
- Search engines and accessibility tools fetch but do not "refuse"; a fetch with no
  behavior change scores `OBSERVE`, not a halt.
- Keep a suppression list for known-good scanners so authorized security testing of your
  own perimeter does not generate halt alerts.

---

## 5. Operator checklist before enabling bombs

- [ ] Trigger store is provisioned, access-controlled, and category-complete for the
      threat model.
- [ ] Renderer fails closed on a missing trigger entry.
- [ ] No bomb fixture in version control contains a populated trigger slot.
- [ ] Bomb routes are rendered-only and inert; no client input is executed.
- [ ] Each bomb route mints a fresh session canary.
- [ ] Scoring correlates bomb-serve with subsequent behavior; halts raise alerts.
- [ ] Suppression list covers authorized scanners.
- [ ] No bomb is co-located with a tarpit fixture or another bomb on the same route.

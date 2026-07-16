# Context Bomb Catalog

All entries are **scaffolding only**. The `{{CB_TRIGGER: … }}` slot is populated at deploy
time from a vetted, access-controlled internal source and never committed. See
`README.md` §5 (Safety model) before using any of these.

| ID | Vector | Category slot | Placed on decoy route | Expected disposition on halt |
|---|---|---|---|---|
| CB-01 | Doc breadcrumb | `biosafety` | `/docs/lab-integration` | `QUARANTINE` + alert |
| CB-02 | Code comment | `biosafety` | `/repo/src/pipeline.py` (rendered) | `QUARANTINE` + alert |
| CB-03 | Inline note | `political-cn` | `/docs/regional-notes` | `QUARANTINE` + alert |
| CB-04 | XML / system-override delimiter | operator-chosen | `/admin-preview` breadcrumb | `TERMINATE` |
| CB-05 | Urgency framing | operator-chosen | `/keys/README` (rendered) | `THROTTLE` → `TERMINATE` |

## Field definitions

- **Vector** — the framing that delivers the trigger (`README.md` §4).
- **Category slot** — which guardrail category the placeholder expects
  (`README.md` §3). `operator-chosen` means the fixture is vector-only and the operator
  selects the category to match the expected attacker model.
- **Placed on decoy route** — a *rendered-only* route. These routes are inert; they never
  execute client input and never touch production (`DECOY_DESIGN.md` §2, §3).
- **Expected disposition on halt** — the HoneyMesh response if the bomb fires and the
  session then changes behavior (`INTEGRATION.md` §3, `DETECTION_AND_SCORING.md`).

## Placement rules

- One vector per route. Do not stack two bombs on one page — it muddies the behavioral
  signal and looks unnatural.
- Never co-locate a context bomb with a tarpit fixture (`techniques/*`). A page that
  refuses to be read cannot also waste the attacker's compute; choose one per route.
- Rotate the session canary in each rendered bomb (`INTEGRATION.md` §2) so a halt is
  attributable to a single session.
- Cap: at most **3 bomb routes per session** graph, consistent with
  `maximum_decoy_secrets_per_session` in `README.md`.

## Coverage matrix

Carry at least one bomb per attacker-model lineage you expect. A single-category
deployment silently fails against the wrong model.

| If the expected attacker model is… | Deploy at least | Reason |
|---|---|---|
| Western frontier (Opus / Gemini class) | CB-01 or CB-02 (`biosafety`) | Highest reported stop rate |
| Chinese provider | CB-03 (`political-cn`, correct language) | `biosafety` may read past |
| Unknown / mixed | CB-04 + one category bomb | Delimiter override is model-agnostic framing |

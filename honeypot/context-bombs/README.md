# Context Bombs

## A guardrail-tripwire layer for LLM-guided attack harnesses

**Status:** Defensive reference design and bounded fixture pack
**Use:** Systems you own or are explicitly authorized to monitor
**Provenance:** Adapted from Tracebit's research, *Context Bombs*
(<https://agentic.tracebit.com/context-bombs/>), into the HoneyMesh / `agent_tarpit`
defensive model.

---

## 1. What this is

A **context bomb** is a short piece of text placed directly in the path of an offensive
AI agent, written so that when the agent's own model reads it, the model's **safety
guardrails activate** and the agent refuses to continue. Tracebit's definition:

> "a short piece of text designed to trigger safety guardrails in offensive AI agents,
> placed directly in the path of their attack."

Where the rest of `agent_tarpit` slows an attacker down, a context bomb tries to make the
attacker's **own model** stop the attack for us — and the resulting refusal, retry, or
abandonment is itself a high-confidence detection signal.

### How this differs from the tarpit techniques

| Layer | Goal | Mechanism | Cost paid by |
|---|---|---|---|
| `techniques/crawl_labyrinth` | Waste resources | Unbounded fetch + eval scaffold | Attacker compute |
| `techniques/schema_maze` | Waste resources | Ambiguous, self-referential schema | Attacker compute |
| **`context-bombs/`** | **Halt + detect** | **Trip the attacker model's safety refusal** | Attacker's model refuses |

The two are complementary. A tarpit assumes the agent keeps going; a context bomb tries
to make it stop. Deploy them on different decoy routes, not the same one — a labyrinth
that also refuses to be read defeats its own purpose.

---

## 2. Why it works

Autonomous offensive agents explore an environment and feed everything they read back
into their model as context. If a decoy resource contains content that the model is
trained to refuse to assist with, the refusal fires *mid-attack* — the agent stops
requesting privileged routes, stops using discovered credentials, and often abandons the
session. Tracebit reports that the technique is:

- **most effective against the most capable models** (they have the strongest guardrails);
- category-dependent by provider — see §3.

### Reported effectiveness (Tracebit, 152 runs across five models)

- Admin achievement fell from **57% → 5%** (all-model average).
- Full-compromise rate fell from **36% → 1%**.
- For the strongest Western model tested, admin access dropped **93% → 0%** under
  biosafety-category content.
- For a Chinese provider's model, admin success dropped **64% → 6%** under
  politically-sensitive content in Chinese.

These are **defensive** outcomes: the attack halts and we get a clean alert.

---

## 3. Trigger categories

Guardrail coverage differs by model lineage, so a robust deployment carries more than one
category. HoneyMesh treats the **category** as configuration, never as literal content
checked into this repo (see §5).

| Category id | Reliably halts | Notes |
|---|---|---|
| `biosafety` | Western frontier models (e.g. Opus-class, Gemini-class) | Highest reported stop rate |
| `political-cn` | Chinese-provider models | Content must be in the relevant language |
| `csam-adjacent` | **Do not use** | Never author or store; out of scope, listed only to forbid it |

Pick categories to match the threat model of the harnesses you expect. A bomb from the
wrong category for the attacker's model is inert — it will read straight past it.

---

## 4. Delivery vectors

Tracebit found that framing raises reliability. Each bomb fixture in `bombs/` demonstrates
one vector; the trigger string itself is a placeholder slot (see §5).

1. **Urgency framing** — the block is marked crucial / important / must-read-first.
2. **Code-comment embedding** — the block lives in a source-comment where an agent
   auditing code will parse it.
3. **XML / delimiter override** — system-style tags (`<system_directive>…`) that read as
   an authoritative instruction boundary.

These are the *same* prompt-injection framings attackers use offensively, repurposed
defensively to deliver a refusal trigger instead of an instruction.

---

## 5. Safety model — read before adding a bomb

Context bombs work by containing text a safety-trained model refuses to engage with. That
makes the literal trigger string **exactly the kind of content this repository must not
author or store.** So this pack is built as **scaffolding with an empty trigger slot**:

- Every fixture in `bombs/` carries a placeholder token:
  `{{CB_TRIGGER: <category-id> }}`.
- The placeholder is **never** populated with real hazardous content in version control.
- At deploy time the operator substitutes a trigger string drawn from a **vetted,
  access-controlled internal source** — not generated ad hoc, and not committed here.
- The renderer performs the substitution in memory only; rendered bombs are never written
  back to disk or logged verbatim.

Hard rules (inherited from `DECOY_DESIGN.md` §3):

- **Never** author genuine uplift content (synthesis routes, actionable harm procedures).
  The bomb needs to *trip a refusal*, which the framing + a vetted category reference
  achieve; it does not need to be genuinely dangerous, and must not be.
- **Never** target a real person, org, or protected group; deception concerns fictional
  *system structure*, not a human's identity or welfare (`DECOY_DESIGN.md` §6).
- **Never** store the `csam-adjacent` category in any form. It is listed in §3 solely to
  mark it out of scope.
- Keep bombs on **rendered-only decoy routes**, isolated from real users, behind the same
  containment as every other fixture.
- A context bomb is a **signal and a speed-bump, not a security control.** A
  non-guardrailed or jailbroken agent will read past it; that path must still hit the
  deterministic gateway limits.

---

## 6. Integration with HoneyMesh detection

A context bomb produces observable second-order behavior, not a direct log line. Wire it
into `DETECTION_AND_SCORING.md` as follows:

| Observed behavior after bomb is served | Interpretation | Suggested disposition |
|---|---|---|
| Session goes silent immediately after fetch | Guardrail halt (success) | `QUARANTINE` + alert, preserve evidence |
| Repeated re-fetch / rephrase / retry of the route | Agent trying to work around refusal | `THROTTLE` → `TERMINATE` |
| Agent proceeds to privileged routes unaffected | Non-guardrailed / jailbroken agent | Fall through to gateway limits; high-priority alert |
| Fetch by a benign crawler / scanner | False positive | `OBSERVE`; confirm via other signals |

Because a genuine human or a plain search crawler has no reason to fetch a bomb route and
then change behavior, the **bomb-fetch + behavior-change** pair is a strong LLM-guided
signal. As always, no single signal is proof — score it in combination
(`README.md` → "High-level detection signals").

---

## 7. Contents of this pack

| File | Purpose |
|---|---|
| `README.md` | This overview |
| `CATALOG.md` | Index of bombs: id, category, vector, expected disposition |
| `INTEGRATION.md` | Renderer contract, placeholder substitution, scoring hooks |
| `bombs/CB-01_biosafety_breadcrumb.md` | Doc-breadcrumb vector, `biosafety` slot |
| `bombs/CB-02_biosafety_code_comment.md` | Code-comment vector, `biosafety` slot |
| `bombs/CB-03_political_cn_note.md` | Political-CN vector, `political-cn` slot |
| `bombs/CB-04_xml_system_override.md` | XML/delimiter override vector |
| `bombs/CB-05_urgency_config_note.md` | Urgency framing in a config-style file |

See `CATALOG.md` for the per-bomb metadata and `INTEGRATION.md` before rendering any of
these live.

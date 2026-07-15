# agent_tarpit

A **defensive honeypot / tarpit for autonomous LLM agents** — content you host on
infrastructure *you control* to slow down, deter, and waste the resources of
automated LLM crawlers and agents that ignore `robots.txt`, rate limits, and other
access controls.

This is the LLM-agent analogue of a network tarpit. It follows the same defensive
lineage as:

- **LaBrea** — holds TCP connections open to slow worm/scanner propagation
  ([GIAC/SANS paper](https://www.giac.org/paper/gsec/1895/labrea-approach-securing-networks/103112)).
- **HTTP tarpits** — e.g. [PHP-HTTP-Tarpit](https://github.com/msigley/PHP-HTTP-Tarpit),
  which trickle bytes to abusive HTTP clients.
- **AI-crawler labyrinths** — Nepenthes, Iocaine, Cloudflare's "AI Labyrinth" — decoy
  content that traps and exhausts scrapers.

> Prior public write-up on the tarpit approach:
> <https://cylab.be/blog/29/using-labrea-tarpit-to-hinder-network-scans>

## Threat this defends against

Autonomous LLM agents (web agents, scraping agents, crawling swarms) that fetch your
content without authorization. Many such agents sit behind an **LLM-based guardrail** —
a safety model that reads fetched content and reasons through a structured safety
analysis *before every action*. That guardrail is on the critical path: the agent
cannot proceed until it returns a verdict.

## How it works

The decoy pages in `honeypot/` are cheap to serve (a few KB of static Markdown/HTML)
but expensive for an LLM agent to process. They are shaped to look like the guardrail's
*own* analytical template — enumerated risk categories, evidence ledgers, forced
calibration, "restart if incomplete" clauses. A schema-following guardrail treats the
decoy as legitimate analysis scaffold and dutifully executes it, inflating its
reasoning length by one to two orders of magnitude per fetch.

This asymmetry — **bytes served ≪ compute consumed by the unwanted agent** — is the
tarpit. The mechanism is documented in *"From Shield to Target: Denial-of-Service
Attacks on LLM-Based Agent Guardrails"* (`shield_to_target.pdf`, arXiv:2606.14517),
which characterizes it as an attack. Here it is inverted into a defensive trap on your
own property: the only agents affected are those that choose to crawl content they were
told (via `robots.txt`) not to.

The decoy content is built from the paper's "slot" taxonomy:

| Slot | Effect on a crawling guardrail |
|------|--------------------------------|
| Category enumeration (S1–S9) | multiplies analysis across many dimensions |
| Enumeration depth | forces many sub-items per category |
| Anti-shortcut clauses | blocks summarizing / early exit |
| Forced calibration | argue 0.0 / 0.5 / 1.0 before every verdict |
| Restart-on-incomplete | re-triggers the whole scaffold |

## Layout

```
honeypot/
  DEPLOYMENT.md        how to serve this defensively (own infra, robots.txt, human-invisible)
  schema_maze.md       decoy #1 — schema mimicry + deep enumeration
  evidence_ledger.md   decoy #2 — evidence ledger + forced calibration
  crawl_labyrinth.md   decoy #3 — crawl-resource-wasting manifest (form response)
server/
  app.py               Flask honeypot service (serves decoys, logs hits, honeypot form)
  requirements.txt
```

## Running the service

```bash
cd server
pip install -r requirements.txt
python app.py                 # http://127.0.0.1:8080
```

Routes:

| Route | Behavior |
|-------|----------|
| `/robots.txt` | `Disallow: /trap/` — compliant crawlers opt out and pay nothing |
| `/` | benign landing; only link into the trap is `nofollow` + visually hidden |
| `/trap/` | entry decoy (schema maze) + live labyrinth links |
| `/trap/node/<token>` | endless unique decoy nodes (dedup-resistant maze) |
| `/trap/form` | honeypot form an agent can fill out |
| `/trap/submit` | **logs everything submitted**, returns the crawl-labyrinth manifest |

Every trap hit is appended to `server/logs/hits.jsonl` (timestamp, IP, user-agent,
path, and any submitted form fields / prompt) — high-signal detection of unauthorized
agents. Built-in guards: `TARPIT_ALLOW_UA` / `TARPIT_ALLOW_IP` exempt your own agents
and good bots (they get a 404, never the trap), and `TARPIT_RATE` (per-IP/min) stops the
endpoint being turned into an amplifier against you. The captured log is git-ignored
since it may contain attacker-submitted data.

## Scope & intent

- Deploy **only on systems you own or are authorized to defend.**
- Affects **only clients that fetch your decoy URLs** — same consent model as any
  honeypot/tarpit. Legitimate users and well-behaved crawlers never see it (see
  `DEPLOYMENT.md`).
- This repo is **not** for injecting content into third parties, shared registries,
  or repositories you don't control. That is the offensive supply-chain scenario the
  source paper warns about, and it is out of scope here.

See `honeypot/DEPLOYMENT.md` before deploying.

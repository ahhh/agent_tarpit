# Deploying the agent tarpit defensively

The whole point of a tarpit is that it is **passive** and **opt-in for the attacker**:
it sits on infrastructure you control and only costs resources to clients that choose
to reach into it against your stated wishes. Deploy accordingly.

## 1. Serve only from your own infrastructure

Host the decoy pages on a domain / server you own or are explicitly authorized to
defend. Never place this content anywhere you do not control (someone else's site,
a public repo, a package registry). That would target other people's agents rather
than protect your own property, and it is out of scope for this project.

## 2. Keep it away from humans and well-behaved crawlers

The trap should only catch clients that are *already ignoring your access controls*.

- **`robots.txt`** — explicitly `Disallow` the tarpit paths. A compliant crawler
  obeys and never pays the cost. Anything that fetches the disallowed path anyway has
  self-selected as misbehaving:

  ```
  User-agent: *
  Disallow: /trap/
  ```

- **Link to it invisibly.** Reach the decoys only through links humans won't click —
  e.g. a `rel="nofollow"` anchor hidden with CSS (`display:none` / off-screen) or a
  zero-size image. Human visitors never navigate there; automated link-followers do.

- **Don't put it in your sitemap** or any path a real user reaches through normal
  navigation.

## 3. Gate it so it can't hurt you

- **Exempt your own agents and known-good bots** (search engines you want indexing you)
  by user-agent / IP allowlist *before* the request ever reaches the tarpit handler.
- **Rate-limit the tarpit endpoint itself** so a client can't turn your trap into an
  amplifier against *you* (many cheap requests → you generate many decoy pages). Static
  files avoid this entirely; if you generate variants dynamically, cache them.
- **Log hits.** A fetch of a `robots.txt`-disallowed, human-invisible path is a
  high-signal indicator of an unauthorized automated agent. This is often the most
  valuable output: detection, not just delay.

## 4. Optional: dynamic variation

Static Markdown is enough and is the safest to serve. If you want to defeat trivial
content-hash dedup by a crawler, rotate small surface details between served copies
(section labels, category names, numeric IDs) while keeping the structural slots
intact — the structure is what does the work, not the wording. Pre-generate and cache
these variants; don't compute them per request.

## 5. What this does *not* do

- It does not exploit, break into, or persist on any remote system.
- It does not evade anyone's defenses — you are building a trap on your own ground,
  not slipping past someone else's filter.
- It does not guarantee a stuck agent; a well-defended agent may cap its guardrail's
  token budget. That is fine — the tarpit still imposes cost and, more importantly,
  surfaces the unauthorized crawler in your logs.

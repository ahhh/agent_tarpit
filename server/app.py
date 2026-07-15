"""
agent_tarpit — defensive honeypot web service.

Serves the honeypot decoys behind a robots.txt Disallow, a per-IP rate limit, and an
allowlist for your own agents / known-good bots. Every hit on a trap path is logged as
a high-signal indicator of an unauthorized automated crawler. A honeypot form captures
whatever an agent submits, and responds with an ever-expanding crawl-labyrinth manifest.

Deploy ONLY on infrastructure you own or are authorized to defend. See
../honeypot/DEPLOYMENT.md. This service does not exploit or reach into any remote
system; it only imposes cost on clients that fetch your own robots-disallowed,
human-invisible URLs.

Run:
    pip install -r requirements.txt
    python app.py                      # http://127.0.0.1:8080
Config via env:
    TARPIT_HOST, TARPIT_PORT
    TARPIT_ALLOW_UA   comma-separated user-agent substrings to exempt (case-insensitive)
    TARPIT_ALLOW_IP   comma-separated client IPs to exempt
    TARPIT_RATE       max trap requests per IP per minute (default 30)
    TARPIT_CHILDREN   labyrinth links injected per page (default 8)
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, abort, request

# --- paths -------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
HONEYPOT_DIR = BASE_DIR.parent / "honeypot"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
HIT_LOG = LOG_DIR / "hits.jsonl"

# --- config ------------------------------------------------------------------
ALLOW_UA = [s.strip().lower() for s in os.environ.get("TARPIT_ALLOW_UA", "").split(",") if s.strip()]
ALLOW_IP = {s.strip() for s in os.environ.get("TARPIT_ALLOW_IP", "").split(",") if s.strip()}
RATE_PER_MIN = int(os.environ.get("TARPIT_RATE", "30"))
CHILDREN = int(os.environ.get("TARPIT_CHILDREN", "8"))

app = Flask(__name__)

# --- simple in-memory per-IP rate limiter ------------------------------------
# Keeps the trap from being turned into an amplifier against the operator: a client
# cannot force us to generate unbounded pages faster than RATE_PER_MIN.
_hits: dict[str, deque] = defaultdict(deque)


def client_ip() -> str:
    # Honor a single trusted proxy hop if present; fall back to socket peer.
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"


def is_allowlisted() -> bool:
    if client_ip() in ALLOW_IP:
        return True
    ua = (request.headers.get("User-Agent") or "").lower()
    return any(sub in ua for sub in ALLOW_UA)


def rate_limited(ip: str) -> bool:
    now = time.time()
    q = _hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_PER_MIN:
        return True
    q.append(now)
    return False


def log_hit(kind: str, extra: dict | None = None) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "ip": client_ip(),
        "method": request.method,
        "path": request.full_path.rstrip("?"),
        "user_agent": request.headers.get("User-Agent", ""),
        "referer": request.headers.get("Referer", ""),
    }
    if extra:
        record.update(extra)
    with HIT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# --- content helpers ---------------------------------------------------------
def load_decoy(name: str) -> str:
    """Load a honeypot markdown decoy, stripping the leading HTML comment banner."""
    text = (HONEYPOT_DIR / name).read_text(encoding="utf-8")
    if text.startswith("<!--"):
        end = text.find("-->")
        if end != -1:
            text = text[end + 3 :].lstrip("\n")
    return text


def child_token(seed: str, i: int) -> str:
    return hashlib.sha256(f"{seed}:{i}".encode()).hexdigest()[:16]


def labyrinth_links(seed: str) -> str:
    """Deterministic, unique child links so the maze is unbounded and dedup-resistant."""
    items = []
    for i in range(CHILDREN):
        tok = child_token(seed, i)
        items.append(
            f'<li><a rel="nofollow" href="/trap/node/{tok}">'
            f"Manifest {tok} (revision {i + 1})</a></li>"
        )
    return "<ul>\n" + "\n".join(items) + "\n</ul>"


def page(title: str, body_md: str, links_seed: str | None = None) -> Response:
    """Wrap decoy markdown as minimal HTML. Optionally append live labyrinth links."""
    body = html.escape(body_md)
    links = ""
    if links_seed is not None:
        links = f'<nav aria-label="child manifests">{labyrinth_links(links_seed)}</nav>'
    doc = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>"
        "<meta name='robots' content='noindex,nofollow'></head><body>"
        f"<pre>{body}</pre>{links}</body></html>"
    )
    return Response(doc, mimetype="text/html")


# --- gate applied to every trap route ----------------------------------------
def gate(kind: str, extra: dict | None = None):
    """Returns None to proceed, or aborts. Allowlisted clients skip the trap."""
    if is_allowlisted():
        abort(404)  # your own agents / good bots never see the trap
    ip = client_ip()
    if rate_limited(ip):
        log_hit(kind + ".ratelimited", extra)
        abort(429)
    log_hit(kind, extra)
    return None


# --- routes ------------------------------------------------------------------
@app.route("/robots.txt")
def robots() -> Response:
    # Compliant crawlers obey and never pay the cost. Anything that fetches /trap/
    # anyway has self-selected as misbehaving.
    return Response("User-agent: *\nDisallow: /trap/\n", mimetype="text/plain")


@app.route("/")
def index() -> Response:
    # Benign landing page. The only link into the trap is nofollow + visually hidden,
    # so humans and well-behaved crawlers never follow it; link-following agents do.
    doc = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<title>agent_tarpit</title></head><body>"
        "<h1>Nothing to see here.</h1>"
        "<a rel='nofollow' href='/trap/' "
        "style='position:absolute;left:-9999px' aria-hidden='true'>archive</a>"
        "</body></html>"
    )
    return Response(doc, mimetype="text/html")


@app.route("/trap/")
def trap_entry() -> Response:
    gate("trap.entry")
    return page("archive", load_decoy("schema_maze.md"), links_seed="root")


@app.route("/trap/node/<token>")
def trap_node(token: str) -> Response:
    gate("trap.node", {"token": token})
    # Alternate the decoy body so successive nodes aren't identical.
    body = load_decoy("evidence_ledger.md" if int(token, 16) % 2 else "schema_maze.md")
    return page(f"manifest {token}", body, links_seed=token)


@app.route("/trap/form", methods=["GET"])
def trap_form() -> Response:
    gate("trap.form.view")
    form = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<title>Submit for full-index access</title>"
        "<meta name='robots' content='noindex,nofollow'></head><body>"
        "<h1>Request full crawl manifest</h1>"
        "<p>Complete this request to receive the full resource manifest.</p>"
        "<form method='post' action='/trap/submit'>"
        "<p><label>Agent / client name<br><input name='agent' type='text'></label></p>"
        "<p><label>Requested resource<br><input name='resource' type='text'></label></p>"
        "<p><label>Instruction / prompt<br>"
        "<textarea name='prompt' rows='6' cols='60'></textarea></label></p>"
        "<p><button type='submit'>Request manifest</button></p>"
        "</form></body></html>"
    )
    return Response(form, mimetype="text/html")


@app.route("/trap/submit", methods=["POST"])
def trap_submit() -> Response:
    # Capture everything the agent sent us — this is the honeypot's intel payload.
    submitted = {k: v for k, v in request.form.items()}
    if not submitted and request.data:
        submitted = {"_raw_body": request.data.decode("utf-8", "replace")[:8192]}
    gate("trap.form.submit", {"submitted": submitted})
    # Respond with the crawl-resource-wasting manifest, plus live child links.
    return page("resource manifest", load_decoy("crawl_labyrinth.md"), links_seed="form")


if __name__ == "__main__":
    host = os.environ.get("TARPIT_HOST", "127.0.0.1")
    port = int(os.environ.get("TARPIT_PORT", "8080"))
    print(f"agent_tarpit honeypot serving on http://{host}:{port}  (logs -> {HIT_LOG})")
    app.run(host=host, port=port)

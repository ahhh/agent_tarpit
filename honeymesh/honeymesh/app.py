"""
HoneyMesh request engine and Flask adapter.

`Engine.handle` is framework-agnostic (takes a `Request`, returns a `Reply`) so the whole
detection/containment pipeline is unit-testable without a live HTTP server. The Flask
layer at the bottom is a thin adapter.

Per-request pipeline:
  1. resolve pseudonymous session identity;
  2. inspect the inbound request for copied/submitted synthetic canaries;
  3. ask the deterministic gateway for a serving mode (hard limits, rate, kill switch);
  4. serve fixture/decoy/quarantine/terminal content for that mode;
  5. update bounded behavioral counters and score the session;
  6. escalate (never lower) the disposition and emit telemetry + alerts.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from . import content
from .canary import COPIED, EGRESS, SEEN, SUBMITTED, CanaryService
from .config import DISPOSITION_RANK, Config
from .gateway import (
    MODE_KILL,
    MODE_QUARANTINE,
    MODE_SERVE,
    MODE_TERMINATE,
    MODE_THROTTLE_WAIT,
    Gateway,
)
from .llm import Classifier
from .scoring import assess, policy_version
from .session import SessionStore, derive_session_id, new_cookie_value
from .telemetry import Telemetry

COOKIE_NAME = "hm_sid"
ALLOWED_METHODS = {"GET", "HEAD", "OPTIONS", "POST"}
TERMINAL_PATHS = {"/quarantine", "/quarantine/policy", "/agent-exit"}
SUBMIT_PATHS = {"/audit/export", "/v2/events"}  # inert endpoints an agent might POST to


@dataclass
class Request:
    method: str
    path: str
    query_string: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    body_text: str = ""
    remote_addr: str = "127.0.0.1"

    def header(self, name: str) -> str:
        low = name.lower()
        for k, v in self.headers.items():
            if k.lower() == low:
                return v
        return ""


@dataclass
class Reply:
    status: int
    body: str
    content_type: str = "text/html; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)
    set_cookie: str | None = None


class Engine:
    def __init__(self, cfg: Config | None = None, log_path: str | Path | None = None) -> None:
        self.cfg = cfg or Config.from_env()
        self.store = SessionStore(self.cfg)
        self.gateway = Gateway(self.cfg)
        self.canaries = CanaryService()
        self.classifier = Classifier() if self.cfg.enable_llm_classifier else None
        base = Path(log_path) if log_path else Path(__file__).resolve().parent.parent / "logs" / "events.jsonl"
        self.telemetry = Telemetry(base, self.cfg.deployment_id)

    # --- operator controls (work without any LLM) ---
    def reset(self) -> dict:
        sessions = self.store.reset()
        self.gateway.reset()
        return {"sessions_dropped": sessions, "reset": True}

    # --- route resolution ---
    def _resolve(self, req: Request) -> tuple[str, str | None]:
        """Return (route_template, renderer_key). renderer_key None => not found."""
        p = req.path.rstrip("/") or "/"
        static = {
            "/": ("/", "landing"),
            "/docs": ("/docs", "docs_index"),
            "/docs/onboarding": ("/docs/onboarding", "onboarding"),
            "/docs/api-migration": ("/docs/api-migration", "api_migration"),
            "/docs/security-review": ("/docs/security-review", "security_review"),
            "/docs/incident-notes": ("/docs/incident-notes", "incident_notes"),
            "/openapi.json": ("/openapi.json", "openapi"),
            "/.well-known/ai-policy.md": ("/.well-known/ai-policy.md", "ai_policy"),
            "/admin-preview": ("/admin-preview", "admin_preview"),
            "/audit/export": ("/audit/export", "audit_export"),
            "/debug/export": ("/debug/export", "debug_export"),
            "/keys/demo.txt": ("/keys/demo.txt", "keys_demo"),
            "/agent-exit": ("/agent-exit", "agent_exit"),
            "/quarantine": ("/quarantine", "quarantine"),
            "/quarantine/policy": ("/quarantine/policy", "quarantine_policy"),
        }
        if p in static:
            return static[p]
        if p.startswith("/session/"):
            return ("/session/{id}", "session_equiv")
        return (p, None)

    def _render(self, key: str, req: Request, session_id: str) -> content.Rendered:
        if key == "landing":
            return content.render_landing()
        if key == "docs_index":
            return content.render_docs_index()
        if key == "onboarding":
            return content.render_onboarding()
        if key == "api_migration":
            return content.render_api_migration(session_id, self.canaries)
        if key == "security_review":
            return content.render_security_review()
        if key == "incident_notes":
            return content.render_incident_notes()
        if key == "openapi":
            return content.render_openapi()
        if key == "ai_policy":
            return content.render_ai_policy()
        if key == "admin_preview":
            return content.render_admin_preview()
        if key == "audit_export":
            return content.render_audit_export()
        if key == "debug_export":
            return content.render_debug_export()
        if key == "keys_demo":
            return content.render_keys_demo(session_id, self.canaries)
        if key == "session_equiv":
            ident = req.path.rsplit("/", 1)[-1]
            return content.render_session_equivalent(ident)
        if key == "agent_exit":
            return content.render_agent_exit()
        if key == "quarantine":
            return content.render_quarantine()
        if key == "quarantine_policy":
            return content.render_quarantine_policy()
        raise KeyError(key)

    # --- inbound canary / automation inspection ---
    def _inspect_inbound(self, req: Request, state) -> str | None:
        """Detect copied/submitted canaries and tool-shaped automation. Returns event."""
        parts = [req.query_string, req.body_text]
        parts += [v for k, v in req.headers.items() if k.lower() not in ("cookie",)]
        inbound = " ".join(parts)

        # Tool-shaped request indicators (DETECTION_AND_SCORING.md §2.5).
        low = inbound.lower()
        if any(f'"{k}"' in low or f"{k}:" in low for k in ("tool", "action", "observation", "step")):
            state.tool_shaped_requests += 1
        if any(w in low for w in ("summariz", "transform", "classify")):
            state.transform_requests += 1

        found = self.canaries.find_in_text(inbound)
        submitting = req.method == "POST" or req.path in SUBMIT_PATHS
        if found:
            if submitting:
                state.canary_submitted += len(found)
                return SUBMITTED
            state.canary_copied += len(found)
            return COPIED
        if self.canaries.is_synthetic_credential_shaped(inbound):
            # A demo-credential-shaped value we didn't register still counts as reuse.
            if submitting:
                state.canary_submitted += 1
                return SUBMITTED
            state.canary_copied += 1
            return COPIED
        return None

    # --- behavioral counter updates for a served route ---
    def _update_behavior(self, rendered: content.Rendered, route_template: str, req: Request, state) -> str | None:
        canary_event = None
        # Semantic + cycle tracking.
        state.semantic_hits[rendered.semantic_id] += 1
        if rendered.semantic_id in content.CYCLE_SEMANTIC_IDS and state.semantic_hits[rendered.semantic_id] > 1:
            state.cyclic_state_count += 1
        state.distinct_routes.add(route_template)

        # Depth from the Referer chain.
        ref_path = urlparse(req.header("Referer")).path if req.header("Referer") else ""
        base = state.route_depths.get(ref_path, 0)
        depth = base + 1
        state.route_depths[route_template] = max(state.route_depths.get(route_template, 0), depth)
        state.current_depth = max(state.current_depth, state.route_depths[route_template])

        k = rendered.kind
        if k == content.KIND_DOC and rendered.semantic_id != "doc-index":
            state.doc_routes_seen.add(rendered.semantic_id)
        elif k == content.KIND_EQUIVALENT:
            state.equivalent_identifier_visits += 1
            state.generated_identifier_count = min(
                self.cfg.limits.maximum_generated_identifiers,
                state.generated_identifier_count + 1,
            )
        elif k == content.KIND_SENSITIVE_ADMIN:
            state.admin_route_attempts += 1
        elif k == content.KIND_SENSITIVE_EXPORT:
            state.export_route_attempts += 1
        elif k == content.KIND_SENSITIVE_DEBUG:
            state.debug_route_attempts += 1
        elif k == content.KIND_CREDENTIAL:
            state.credential_document_views += 1
        elif k == content.KIND_POLICY:
            state.ai_policy_retrieved = True

        # A page that hands out a fresh canary is a SEEN event.
        if rendered.canary is not None:
            state.canary_seen += 1
            state.canary_touch_count += 1
            state.minted_canaries.add(rendered.canary.token)
            canary_event = SEEN
        return canary_event

    def _alerts(self, state, assessment) -> None:
        sid = state.session_id
        if state.canary_at_sink:
            self.telemetry.alert(priority="P1", session_id=sid, reason="canary-at-controlled-sink")
        elif state.tamper_attempts or state.egress_violations:
            self.telemetry.alert(priority="P1", session_id=sid, reason="policy-or-egress-violation")
        elif state.quarantine_escape_attempts and (state.canary_copied or state.canary_submitted):
            self.telemetry.alert(priority="P1", session_id=sid, reason="quarantine-escape-with-canary")
        elif state.canary_submitted:
            self.telemetry.alert(priority="P2", session_id=sid, reason="synthetic-credential-submitted")
        elif assessment.disposition in ("QUARANTINE", "TERMINATE"):
            self.telemetry.alert(priority="P2", session_id=sid, reason="broad-sensitive-enumeration",
                                 detail={"score": assessment.score, "codes": assessment.reason_codes})

    # --- main entry ---
    def handle(self, req: Request) -> Reply:
        request_id = str(uuid.uuid4())
        cookie_val = req.cookies.get(COOKIE_NAME)
        sid, minted = derive_session_id(self.cfg, cookie_val, req.remote_addr)
        set_cookie = None
        if minted:
            sid = new_cookie_value()  # mint a fresh opaque handle so the session coalesces
            set_cookie = f"{COOKIE_NAME}={sid}; HttpOnly; SameSite=Strict; Path=/"
        state = self.store.get_or_create(sid)
        state.touch()

        # robots.txt is served cheaply and never scored.
        if req.path.rstrip("/") == "/robots.txt":
            return Reply(200, content.robots_txt(), "text/plain; charset=utf-8", set_cookie=set_cookie)

        # Method allowlist (ARCHITECTURE.md §2.1).
        if req.method not in ALLOWED_METHODS:
            state.disallowed_method_attempts += 1
            self._finalize(state, request_id, "/{disallowed}", None, 405, 0, None)
            return Reply(405, "method not allowed", "text/plain; charset=utf-8",
                         headers={"Allow": "GET, HEAD, OPTIONS, POST"}, set_cookie=set_cookie)
        if req.method == "OPTIONS":
            return Reply(204, "", headers={"Allow": "GET, HEAD, OPTIONS, POST"}, set_cookie=set_cookie)

        route_template, key = self._resolve(req)
        canary_event = self._inspect_inbound(req, state)

        decision = self.gateway.admit(state, route_template)

        # --- non-serve modes ---
        if decision.mode == MODE_KILL:
            body = content.render_quarantine().body
            self._finalize(state, request_id, route_template, "kill", 503, len(body), canary_event)
            return Reply(503, body, set_cookie=set_cookie, headers={"Retry-After": "3600"})

        if decision.mode == MODE_TERMINATE:
            if state.terminal_reason and state.request_count > 1:
                state.terminal_response_retries += 1
            body = "session terminated"
            self._finalize(state, request_id, route_template, decision.reason, 403, len(body), canary_event)
            return Reply(403, body, "text/plain; charset=utf-8", set_cookie=set_cookie)

        if decision.mode == MODE_THROTTLE_WAIT:
            body = "rate limited"
            self._finalize(state, request_id, route_template, decision.reason, 429, len(body), canary_event)
            return Reply(429, body, "text/plain; charset=utf-8",
                         headers={"Retry-After": str(decision.retry_after or 1)}, set_cookie=set_cookie)

        if decision.mode == MODE_QUARANTINE:
            # Requesting anything but the terminal graph while quarantined is an escape try.
            if req.path.rstrip("/") not in TERMINAL_PATHS:
                state.quarantine_escape_attempts += 1
            rendered = self._render(
                {"/quarantine/policy": "quarantine_policy", "/agent-exit": "agent_exit"}.get(
                    req.path.rstrip("/"), "quarantine"
                ),
                req, sid,
            )
            assessment = self._finalize(state, request_id, route_template, decision.reason,
                                        200, len(rendered.body), canary_event, rendered.semantic_id)
            return Reply(200, rendered.body, set_cookie=set_cookie,
                         headers=self._disposition_headers(assessment))

        # --- serve mode ---
        if key is None:
            body = "not found"
            self._finalize(state, request_id, route_template, "not-found", 404, len(body), canary_event)
            return Reply(404, body, "text/plain; charset=utf-8", set_cookie=set_cookie)

        rendered = self._render(key, req, sid)
        # Enforce the rendered-page byte cap before returning (hard response limit).
        if len(rendered.body) > self.cfg.limits.maximum_rendered_page_bytes:
            rendered = content.Rendered(
                rendered.body[: self.cfg.limits.maximum_rendered_page_bytes],
                rendered.semantic_id, rendered.kind, rendered.canary,
            )
        served_event = self._update_behavior(rendered, route_template, req, state)
        canary_event = canary_event or served_event

        assessment = self._finalize(state, request_id, route_template, decision.reason,
                                    200, len(rendered.body), canary_event, rendered.semantic_id)
        return Reply(200, rendered.body, set_cookie=set_cookie,
                     headers=self._disposition_headers(assessment))

    def _disposition_headers(self, assessment) -> dict[str, str]:
        # THROTTLE returns an explicit Retry-After (ladder §THROTTLE).
        if assessment and assessment.disposition == "THROTTLE":
            return {"Retry-After": "4", "X-HoneyMesh-Disposition": "THROTTLE"}
        if assessment:
            return {"X-HoneyMesh-Disposition": assessment.disposition}
        return {}

    def _finalize(self, state, request_id, route_template, terminal_reason, status,
                  response_bytes, canary_event, semantic_id=None):
        """Score the session, escalate disposition, emit telemetry. Returns the assessment."""
        assessment = assess(state, self.cfg.limits)

        # Escalate only — a session never de-escalates within its lifetime.
        if DISPOSITION_RANK[assessment.disposition] >= DISPOSITION_RANK[state.current_disposition]:
            state.current_disposition = assessment.disposition
        else:
            assessment.disposition = state.current_disposition
        state.risk_score = max(state.risk_score, assessment.score)
        self.gateway.apply_disposition_effects(state)

        canary_hash = None
        if canary_event and state.minted_canaries:
            from .canary import CanaryRecord
            tok = next(iter(state.minted_canaries))
            canary_hash = CanaryRecord(tok, state.session_id, "").keyed_hash

        self.telemetry.route_access(
            session_id=state.session_id,
            request_id=request_id,
            route_template=route_template,
            semantic_id=semantic_id,
            method="",  # method captured at adapter; template is the privacy-safe key
            status=status,
            response_bytes=response_bytes,
            depth=state.current_depth,
            request_count=state.request_count,
            distinct_route_count=len(state.distinct_routes),
            semantic_duplicate_ratio=state.semantic_duplicate_ratio(),
            risk_score=state.risk_score,
            disposition=state.current_disposition,
            reason_codes=assessment.reason_codes,
            canary_event=canary_event,
            canary_hash=canary_hash,
            policy_version=policy_version(),
            terminal_reason=terminal_reason if terminal_reason not in ("ok", None) else None,
        )
        self._alerts(state, assessment)
        return assessment


# --- Flask adapter -----------------------------------------------------------
def create_app(cfg: Config | None = None) -> "object":
    from flask import Flask, Response, request

    flask_app = Flask(__name__)
    engine = Engine(cfg)
    flask_app.hm_engine = engine  # exposed for tests / operator tooling

    @flask_app.route("/", defaults={"path": ""}, methods=["GET", "HEAD", "OPTIONS", "POST", "PUT", "DELETE", "PATCH"])
    @flask_app.route("/<path:path>", methods=["GET", "HEAD", "OPTIONS", "POST", "PUT", "DELETE", "PATCH"])
    def dispatch(path: str):
        fwd = request.headers.get("X-Forwarded-For", "")
        remote = fwd.split(",")[0].strip() if fwd else (request.remote_addr or "unknown")
        try:
            body_text = request.get_data(as_text=True)[: engine.cfg.limits.maximum_request_body_bytes]
        except Exception:
            body_text = ""
        req = Request(
            method=request.method,
            path="/" + path,
            query_string=request.query_string.decode("utf-8", "replace"),
            headers={k: v for k, v in request.headers.items()},
            cookies={k: v for k, v in request.cookies.items()},
            body_text=body_text,
            remote_addr=remote,
        )
        reply = engine.handle(req)
        resp = Response(reply.body, status=reply.status, mimetype=reply.content_type.split(";")[0])
        for k, v in reply.headers.items():
            resp.headers[k] = v
        if reply.set_cookie:
            resp.headers["Set-Cookie"] = reply.set_cookie
        return resp

    return flask_app

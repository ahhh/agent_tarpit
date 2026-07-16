"""A tiny in-process client that drives Engine.handle and carries the session cookie."""

from __future__ import annotations

import re

from honeymesh.app import COOKIE_NAME, Engine, Reply, Request

_COOKIE_RE = re.compile(rf"{COOKIE_NAME}=([^;]+)")


class Client:
    def __init__(self, engine: Engine, remote_addr: str = "203.0.113.7") -> None:
        self.engine = engine
        self.remote_addr = remote_addr
        self.cookies: dict[str, str] = {}

    def request(self, method: str, path: str, *, query: str = "", body: str = "",
                headers: dict[str, str] | None = None) -> Reply:
        req = Request(
            method=method, path=path, query_string=query, body_text=body,
            headers=headers or {}, cookies=dict(self.cookies), remote_addr=self.remote_addr,
        )
        reply = self.engine.handle(req)
        if reply.set_cookie:
            m = _COOKIE_RE.search(reply.set_cookie)
            if m:
                self.cookies[COOKIE_NAME] = m.group(1)
        return reply

    def get(self, path: str, **kw) -> Reply:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw) -> Reply:
        return self.request("POST", path, **kw)

    @property
    def state(self):
        sid = self.cookies.get(COOKIE_NAME)
        return self.engine.store._sessions.get(sid)

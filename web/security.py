"""Loopback security middleware for AksaraSight Web UI."""

import re
from typing import Any, Callable
from urllib.parse import urlsplit

_LOOPBACK_HOST_PATTERN = re.compile(r"^(127\.0\.0\.1|localhost)(:\d+)?$")


class LoopbackSecurityMiddleware:
    """Pure ASGI middleware enforcing loopback-only Host and Origin headers.

    Defends against DNS rebinding and cross-site request forgery by rejecting
    any non-loopback Host headers and verifying Origin on mutating requests.
    Does not buffer responses or interfere with SSE streaming.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))

        # 1. Host header validation
        raw_host = headers.get(b"host", b"").decode("latin-1")
        if not raw_host or not _LOOPBACK_HOST_PATTERN.fullmatch(raw_host):
            await send({
                "type": "http.response.start",
                "status": 400,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", b"11"),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": b"Bad Request",
            })
            return

        # 2. Origin header validation for state-mutating methods
        method = scope.get("method", "").upper()
        if method in ("POST", "PUT", "DELETE", "PATCH"):
            raw_origin = headers.get(b"origin")
            if raw_origin is not None:
                origin_str = raw_origin.decode("latin-1")
                netloc = urlsplit(origin_str).netloc
                if not netloc or not _LOOPBACK_HOST_PATTERN.fullmatch(netloc):
                    await send({
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [
                            (b"content-type", b"text/plain; charset=utf-8"),
                            (b"content-length", b"9"),
                        ],
                    })
                    await send({
                        "type": "http.response.body",
                        "body": b"Forbidden",
                    })
                    return

        await self.app(scope, receive, send)

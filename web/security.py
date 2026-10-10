"""Loopback security middleware for AksaraSight Web UI."""

import re
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

_LOOPBACK_HOST_PATTERN = re.compile(r"^(127\.0\.0\.1|localhost)(:\d+)?$")


class LoopbackSecurityMiddleware:
    """Pure ASGI middleware enforcing loopback-only Host and Origin headers.

    Defends against DNS rebinding and cross-site request forgery by rejecting
    any non-loopback Host headers and verifying Origin on mutating requests.
    Supports port pinning to prevent cross-origin requests from other local servers.
    Does not buffer responses or interfere with SSE streaming.
    """

    def __init__(
        self,
        app: Any,
        allowed_port: Optional[int] = None,
        dev_mode: bool = False,
        allowed_dev_ports: tuple[int, ...] = (5173,),
    ) -> None:
        self.app = app
        self.allowed_port = allowed_port
        self.dev_mode = dev_mode
        self.allowed_dev_ports = allowed_dev_ports

    def _is_dev_mode(self, scope: dict[str, Any]) -> bool:
        if self.dev_mode:
            return True
        app = scope.get("app") or self.app
        return bool(getattr(getattr(app, "state", None), "dev_mode", False))

    def _resolve_allowed_port(self, scope: dict[str, Any]) -> Optional[int]:
        if self.allowed_port is not None:
            return self.allowed_port
        app = scope.get("app") or self.app
        app_port = getattr(getattr(app, "state", None), "allowed_port", None)
        if app_port is not None:
            return app_port
        server = scope.get("server")
        if server and len(server) > 1 and server[1] is not None:
            return server[1]
        return None

    def _get_pattern(self, allowed_port: Optional[int]) -> re.Pattern:
        if allowed_port is None:
            return _LOOPBACK_HOST_PATTERN
        if allowed_port == 80:
            return re.compile(r"^(127\.0\.0\.1|localhost)(:80)?$")
        return re.compile(rf"^(127\.0\.0\.1|localhost):{allowed_port}$")

    async def __call__(self, scope: dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        allowed_port = self._resolve_allowed_port(scope)
        pattern = self._get_pattern(allowed_port)

        headers = dict(scope.get("headers", []))

        # 1. Host header validation
        raw_host = headers.get(b"host", b"").decode("latin-1")
        if not raw_host or not pattern.fullmatch(raw_host):
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
                origin_allowed = bool(netloc and pattern.fullmatch(netloc))
                if not origin_allowed and self._is_dev_mode(scope) and netloc:
                    dev_parsed = urlsplit(origin_str)
                    if (
                        dev_parsed.hostname in ("127.0.0.1", "localhost")
                        and dev_parsed.port in self.allowed_dev_ports
                    ):
                        origin_allowed = True

                if not origin_allowed:
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

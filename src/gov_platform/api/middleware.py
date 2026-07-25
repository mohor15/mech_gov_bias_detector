"""Cross-cutting ASGI middleware.

Added during the M0 finalization review to close a concrete, currently-
exploitable gap: neither FastAPI nor uvicorn caps request body size by
default, and the Ingestion API's dict fields have no size/key-count limits
of their own. `MaxBodySizeMiddleware` rejects a request whose declared
`Content-Length` exceeds a configured threshold before it reaches routing
or validation.

This checks `Content-Length` only — a client that omits it or lies about it
(e.g. chunked transfer encoding) is not caught here. That's a deliberate
scope boundary, not an oversight: catching every case requires counting
bytes as they stream in, which belongs with the reverse-proxy / gateway
layer M13 (Deployment Hardening) introduces, not hand-rolled into the
application for one endpoint today. This middleware closes the common case
(every standard HTTP client, including curl/requests/browsers, reports
`Content-Length` honestly) without building infrastructure M13 already owns.

Implemented as raw ASGI middleware rather than Starlette's
`BaseHTTPMiddleware`: this only needs to inspect headers and, in the
oversized case, send a response before the app ever runs — the raw ASGI
`(scope, receive, send)` contract expresses that directly, and avoids
`BaseHTTPMiddleware`'s known interaction issues with streaming responses
that this class has no need to invoke.
"""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class MaxBodySizeMiddleware:
    """Rejects requests whose declared `Content-Length` exceeds `max_bytes`."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        content_length = headers.get(b"content-length")

        if content_length is not None and int(content_length) > self._max_bytes:
            response = JSONResponse(
                status_code=413,
                content={"detail": f"request body exceeds {self._max_bytes} byte limit"},
            )
            await response(scope, receive, send)
            return

        await self._app(scope, receive, send)

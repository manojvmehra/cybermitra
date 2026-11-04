"""HTTP hardening: request-size limits, security headers (CSP with a hash of the inline script), client IP."""

import base64
import hashlib
import re
from pathlib import Path

from starlette.formparsers import MultiPartParser
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings

MAX_AUDIO_BODY = 7 * 1024 * 1024  # multipart audio upload, incl. form overhead
MAX_JSON_BODY = 16 * 1024
PRIVATE_PATHS = ("/api/session", "/api/operator", "/api/events")  # responses carry call data: never cached

# Starlette spools uploads > 1 MB to a temp file on disk. Keep every allowed upload in memory instead:
# the body limit below guarantees nothing larger ever reaches the parser.
MultiPartParser.max_file_size = MAX_AUDIO_BODY
MultiPartParser.max_part_size = MAX_AUDIO_BODY


class BodySizeLimit:
    """Pure-ASGI limit on request body size (works for chunked uploads with no Content-Length too)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = MAX_AUDIO_BODY if scope["path"].endswith("/turn") else MAX_JSON_BODY
        for k, v in scope.get("headers", []):
            if k == b"content-length" and v.isdigit() and int(v) > limit:
                await _reject(send)
                return
        seen = 0
        responded = rejected = False

        async def limited() -> Message:
            nonlocal seen, rejected
            if rejected:
                return {"type": "http.disconnect"}
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > limit:
                    # answer 413 ourselves, then tell the app the client went away; whatever the app
                    # tries to send afterwards is dropped
                    rejected = True
                    if not responded:
                        await _reject(send)
                    return {"type": "http.disconnect"}
            return msg

        async def guarded_send(msg: Message) -> None:
            nonlocal responded
            if rejected:
                return
            if msg["type"] == "http.response.start":
                responded = True
            await send(msg)

        try:
            await self.app(scope, limited, guarded_send)
        except Exception:
            if not rejected:
                raise


async def _reject(send: Send) -> None:
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": b'{"detail":"request too large"}'})


def inline_script_hashes(*html_paths: Path) -> list[str]:
    out = []
    bodies = [b for p in html_paths
              for b in re.findall(r"<script>(.*?)</script>", p.read_text(encoding="utf-8"), flags=re.S)]
    for body in bodies:
        digest = hashlib.sha256(body.encode("utf-8")).digest()
        out.append("'sha256-" + base64.b64encode(digest).decode() + "'")
    return out


class SecurityHeaders:
    def __init__(self, app: ASGIApp, script_hashes: list[str]) -> None:
        self.app = app
        self.csp = "; ".join([
            "default-src 'self'",
            "script-src 'self' " + " ".join(script_hashes),
            "style-src 'self' 'unsafe-inline'",
            "media-src 'self' blob:",
            "img-src 'self' data:",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'none'",
            "frame-ancestors 'none'",
            "form-action 'self'",
        ])

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]

        async def add_headers(msg: Message) -> None:
            if msg["type"] == "http.response.start":
                private = path.startswith(PRIVATE_PATHS)
                h = [(k, v) for k, v in msg.get("headers", []) if k.lower() != b"cache-control" or not private]
                h += [
                    (b"content-security-policy", self.csp.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"permissions-policy", b"microphone=(self), camera=(), geolocation=(), payment=()"),
                    (b"cross-origin-opener-policy", b"same-origin"),
                    (b"cross-origin-resource-policy", b"same-origin"),
                ]
                if private:
                    h.append((b"cache-control", b"no-store"))
                if get_settings().HSTS:
                    h.append((b"strict-transport-security", b"max-age=31536000"))
                msg["headers"] = h
            await send(msg)

        await self.app(scope, receive, add_headers)


def client_ip(request: Request) -> str:
    """Behind a proxy (Render/Railway) set TRUST_PROXY_HEADERS=true to use the left-most X-Forwarded-For hop.
    Never trusted by default: the header is client-controlled."""
    if get_settings().TRUST_PROXY_HEADERS:
        xff = request.headers.get("x-forwarded-for", "")
        first = xff.split(",")[0].strip()
        if first:
            return first[:64]
    return request.client.host if request.client else "unknown"

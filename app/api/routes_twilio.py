"""Experimental telephony routes (CLAUDE.md §6.16). main.py mounts these only when TWILIO_ENABLED is true.

Twilio's webhook is signed, so POST /api/twilio/voice checks the signature. Twilio's docs do not say the media
stream handshake is signed, so the signed webhook issues a one-time token and the stream must present it in its
first message, before any session or API call exists.
"""

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from twilio.request_validator import RequestValidator

from app.api import routes_caller
from app.config import get_settings
from app.dialog import prompts
from app.logging_utils import log
from app.ratelimit import limiter
from app.twilio_bridge import CallBridge

logger = logging.getLogger("api")
router = APIRouter()

STREAM_PATH = "/api/twilio/stream"
START_TIMEOUT_S = 10
TOKEN_TTL_S = 60
MAX_MESSAGES_BEFORE_START = 3
_TOKENS: dict[str, tuple[str, float]] = {}  # one-time stream token -> (CallSid, expiry)


def issue_token(call_sid: str, now: float | None = None) -> str:
    now = now or time.time()
    for tok in [t for t, (_, exp) in _TOKENS.items() if exp < now]:
        _TOKENS.pop(tok, None)
    token = secrets.token_urlsafe(24)
    _TOKENS[token] = (call_sid, now + TOKEN_TTL_S)
    return token


def redeem_token(token: str, call_sid: str, now: float | None = None) -> bool:
    entry = _TOKENS.pop(token, None)  # one use, right or wrong
    return entry is not None and entry[1] >= (now or time.time()) and hmac.compare_digest(entry[0], call_sid)


def public_base(request: Request) -> str:
    """The URL Twilio dialled. Behind a tunnel the app sees http://localhost, so it is rebuilt from the headers."""
    configured = get_settings().TWILIO_PUBLIC_URL.rstrip("/")
    if configured:
        return configured
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", request.url.netloc)
    return f"{proto}://{host}"


def _say_and_hang_up(text: str) -> Response:
    twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Say language="en-IN">{escape(text)}</Say><Hangup/></Response>'
    return Response(twiml, media_type="text/xml")


def _caller_key(number: str) -> str:
    """Rate limits need to tell callers apart, but the number itself is never kept."""
    return hmac.new(get_settings().TWILIO_AUTH_TOKEN.encode(), number.encode(), hashlib.sha256).hexdigest()


@router.post("/api/twilio/voice")
async def voice(request: Request) -> Response:
    settings = get_settings()
    params = {k: str(v) for k, v in (await request.form()).items()}
    url = public_base(request) + request.url.path
    signature = request.headers.get("x-twilio-signature", "")
    if not RequestValidator(settings.TWILIO_AUTH_TOKEN).validate(url, params, signature):
        log(logger, "twilio signature rejected")
        raise HTTPException(403, "invalid signature")
    if settings.TWILIO_ACCOUNT_SID and params.get("AccountSid") != settings.TWILIO_ACCOUNT_SID:
        raise HTTPException(403, "wrong account")

    allowed, why = limiter.allow_session(_caller_key(params.get("From", "")))
    if allowed and len(routes_caller.SESSIONS) >= settings.MAX_ACTIVE_SESSIONS:
        allowed, why = False, "server_busy"
    if not allowed:
        log(logger, "phone call refused", reason=why)
        return _say_and_hang_up(prompts.text("RATE_LIMITED", "en"))

    token = issue_token(params.get("CallSid", ""))
    stream_url = public_base(request).replace("https://", "wss://", 1).replace("http://", "ws://", 1) + STREAM_PATH
    twiml = ('<?xml version="1.0" encoding="UTF-8"?><Response><Connect>'
             f'<Stream url={quoteattr(stream_url)}><Parameter name="token" value={quoteattr(token)}/></Stream>'
             '</Connect><Say language="en-IN">If you need more help, please call 1930.</Say><Hangup/></Response>')
    return Response(twiml, media_type="text/xml")


async def _wait_for_start(ws: WebSocket) -> dict[str, Any] | None:
    for _ in range(MAX_MESSAGES_BEFORE_START):
        msg = json.loads(await ws.receive_text())
        if msg.get("event") == "start":
            return msg
    return None


def _authorised(msg: dict[str, Any]) -> bool:
    start = msg.get("start") or {}
    settings = get_settings()
    if settings.TWILIO_ACCOUNT_SID and start.get("accountSid") != settings.TWILIO_ACCOUNT_SID:
        return False
    token = str((start.get("customParameters") or {}).get("token", ""))
    return redeem_token(token, str(start.get("callSid", "")))


@router.websocket(STREAM_PATH)
async def stream(ws: WebSocket) -> None:
    await ws.accept()
    try:
        msg = await asyncio.wait_for(_wait_for_start(ws), START_TIMEOUT_S)
    except (TimeoutError, WebSocketDisconnect, ValueError):
        msg = None
    if msg is None or not _authorised(msg):
        log(logger, "twilio stream rejected")
        with contextlib.suppress(RuntimeError):
            await ws.close(code=1008)
        return

    start = msg["start"]
    bridge = CallBridge(ws.send_text, ws.close, get_settings().TWILIO_LANG, str(start.get("callSid", ""))[-6:])
    bridge.stream_sid = str(start.get("streamSid", ""))
    worker = asyncio.create_task(bridge.run())
    try:
        while not worker.done():
            try:
                await bridge.on_message(json.loads(await ws.receive_text()))
            except ValueError:
                continue
    except (WebSocketDisconnect, RuntimeError):
        bridge.inbox.put_nowait(("stop", None))
    with contextlib.suppress(WebSocketDisconnect, RuntimeError):
        await worker

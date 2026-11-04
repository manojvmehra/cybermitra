import logging
import re
import time

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app import audio, cache, card
from app.api.schemas import ConfirmIn, CreateSession, NumpadIn, PromptOut, SkipIn, SmsIn, TurnResponse
from app.config import get_settings
from app.dialog import prompts
from app.dialog.models import Action, Event, Session
from app.dialog.state_machine import next_state
from app.gnani import http as gnani_http
from app.gnani import stt, tts
from app.gnani.http import GnaniError
from app.logging_utils import log
from app.nlp import extractor
from app.ratelimit import limiter
from app.security import client_ip

logger = logging.getLogger("api")
router = APIRouter()

SESSIONS: dict[str, Session] = {}
MAX_UPLOAD_BYTES = 6 * 1024 * 1024
_SID = re.compile(r"[0-9a-f]{32}")


def _sweep() -> None:
    ttl = get_settings().SESSION_TTL_S
    now = time.time()
    for sid in [k for k, v in SESSIONS.items() if now - v.last_active > ttl]:
        SESSIONS.pop(sid, None)


def _get(sid: str) -> Session:
    _sweep()
    s = SESSIONS.get(sid) if _SID.fullmatch(sid) else None
    if s is None:
        raise HTTPException(404, "session not found or expired")
    return s


def _banner() -> str | None:
    if not get_settings().DEMO_MODE:
        return None
    return "Demo only — do not enter real details. Synthetic data only."


async def _render_prompts(s: Session, acts: list[Action]) -> PromptOut:
    settings = get_settings()
    texts = [a for a in acts if a.type == "SpeakPrompt" and a.text]
    out = PromptOut(text=" ".join(a.text or "" for a in texts))
    if not settings.TTS_ENABLED or not settings.GNANI_API_KEY:
        return out
    lang = "ta-IN" if s.lang == "ta" else "en-IN"
    for i, a in enumerate(texts):
        speed = settings.TTS_SPEED_READBACK if a.speed == "readback" else settings.TTS_SPEED_PROMPT
        persist = prompts.is_static_text(a.text or "", s.lang)  # anything else may contain the user's digits
        try:
            _, key = await tts.synthesize(a.text or "", lang=lang, speed=speed,  # type: ignore[arg-type]
                                          request_id=f"{s.id}-{s.api_turns}-p{i}", persist=persist)
            out.audio_urls.append(tts.audio_url(key))
        except GnaniError as e:
            log(logger, "tts failed", code=e.code, status=e.status)
            break
    out.audio_url = out.audio_urls[0] if out.audio_urls else None
    return out


def _fields(s: Session) -> dict[str, dict]:
    return {k: {"value": f.value, "display": f.display() if f.value is not None else "—", "status": f.status,
                "source": f.source, "confidence": f.confidence, "corrections": f.corrections, "warn": f.warn}
            for k, f in s.fields.items()}


async def _respond(s: Session, acts: list[Action], transcript: str | None = None,
                   error: str | None = None) -> TurnResponse:
    SESSIONS[s.id] = s
    rb = next((a.data for a in reversed(acts) if a.type == "ShowReadback"), None)
    if s.state != "READBACK":
        rb = None
    numpad = next((a.data for a in reversed(acts) if a.type == "ShowNumpad"), None)
    show_card = s.state == "CARD" or any(a.type == "ShowCard" for a in acts)
    log(logger, "turn", session=s.id[:8], state=s.state, field=s.current_field or "", n_actions=len(acts))
    return TurnResponse(
        session_id=s.id, state=s.state, current_field=s.current_field, transcript=transcript, fields=_fields(s), readback=rb,
        numpad=numpad, prompt=await _render_prompts(s, acts), handoff=s.handoff,
        card=card.render(s) if show_card else None, elapsed_s=s.elapsed_s(), demo_banner=_banner(), error=error,
    )


@router.get("/health")
async def health() -> dict:
    s = get_settings()
    return {"ok": True, "gnani_key_present": bool(s.GNANI_API_KEY), "evon_mode": s.EVON_MODE,
            "ffmpeg": audio.ffmpeg_available(), "app_name": s.APP_NAME}


@router.post("/api/session")
async def create_session(body: CreateSession, request: Request) -> TurnResponse:
    if not body.consent:
        raise HTTPException(400, "consent required")
    ok, why = limiter.allow_session(client_ip(request))
    if ok and len(SESSIONS) >= get_settings().MAX_ACTIVE_SESSIONS:
        _sweep()
        ok, why = len(SESSIONS) < get_settings().MAX_ACTIVE_SESSIONS, "server_busy"
    if not ok:
        lang = body.lang
        return JSONResponse(status_code=429, content={  # type: ignore[return-value]
            "error": why, "prompt": {"text": prompts.text("RATE_LIMITED", lang)}, "call": "1930"})
    _sweep()
    s = Session(lang=body.lang)
    s, acts = next_state(s, Event(type="START"))
    return await _respond(s, acts)


@router.post("/api/session/{sid}/turn")
async def turn(sid: str, audio_file: UploadFile = File(..., alias="audio")) -> TurnResponse:
    s = _get(sid)
    settings = get_settings()
    if s.api_turns >= settings.MAX_TURNS_PER_SESSION:
        return JSONResponse(status_code=429, content={  # type: ignore[return-value]
            "error": "max_turns", "prompt": {"text": prompts.text("RATE_LIMITED", s.lang)}, "call": "1930"})
    raw = await audio_file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "audio too large")
    try:
        wav = await audio.normalize(raw)
    except audio.AudioError:
        s, acts = next_state(s, Event(type="AUDIO_TURN", text=""))
        return await _respond(s, acts, error="audio_decode")
    del raw  # audio lives in memory for this request only
    if audio.duration_s(wav) > settings.MAX_CLIP_S:
        acts = [Action(type="SpeakPrompt", text=prompts.text("TOO_LONG", s.lang))]
        return await _respond(s, acts, error="too_long")

    s = s.model_copy()
    s.api_turns += 1  # every STT call counts toward the per-session cap, even silent clips
    SESSIONS[s.id] = s
    profile = stt.SttProfile.from_settings(s.lang)
    try:
        res = await stt.transcribe(wav, profile=profile, context=s.last_prompt_text or None,
                                   request_id=f"{s.id}-{s.api_turns}", use_cache=settings.STT_CACHE_LIVE)
    except GnaniError as e:
        log(logger, "stt failed", code=e.code, status=e.status)
        acts = [Action(type="SpeakPrompt", text=prompts.text("DIDNT_CATCH", s.lang))]
        return await _respond(s, acts, error=f"stt_{e.code}")
    if res.truncated:
        acts = [Action(type="SpeakPrompt", text=prompts.text("TOO_LONG", s.lang))]
        return await _respond(s, acts, error="truncated")

    candidates = None
    if s.state == "NARRATIVE" and settings.EVON_MODE != "off":
        cands = await extractor.extract_narrative(res)
        candidates = {k: c.__dict__ for k, c in cands.items()}
    ev = Event(type="AUDIO_TURN", text=res.text, literal=res.literal, candidates=candidates)
    s, acts = next_state(s, ev)
    shown = s.transcripts[-1] if s.transcripts else res.text
    return await _respond(s, acts, transcript=shown)


@router.post("/api/session/{sid}/sms")
async def sms(sid: str, body: SmsIn) -> TurnResponse:
    s, acts = next_state(_get(sid), Event(type="SMS_PASTED", text=body.text))
    return await _respond(s, acts)


@router.post("/api/session/{sid}/confirm")
async def confirm(sid: str, body: ConfirmIn) -> TurnResponse:
    s, acts = next_state(_get(sid), Event(type="BUTTON", field=body.field, chunk_index=body.chunk_index,
                                          answer=body.answer))
    return await _respond(s, acts)


@router.post("/api/session/{sid}/numpad")
async def numpad(sid: str, body: NumpadIn) -> TurnResponse:
    s, acts = next_state(_get(sid), Event(type="NUMPAD", field=body.field, digits=body.digits))
    return await _respond(s, acts)


@router.post("/api/session/{sid}/skip")
async def skip(sid: str, body: SkipIn) -> TurnResponse:
    s, acts = next_state(_get(sid), Event(type="SKIP", field=body.field))
    return await _respond(s, acts)


@router.post("/api/session/{sid}/finish")
async def finish(sid: str) -> TurnResponse:
    """Jump straight to the card (user pressed 'Make card now')."""
    s = _get(sid).model_copy(deep=True)
    if s.state not in ("HANDOFF_NONFIN", "HANDOFF_WELLBEING"):
        s.state = "CARD"
    return await _respond(s, [Action(type="ShowCard")])


@router.get("/api/session/{sid}/card")
async def get_card(sid: str) -> dict:
    s = _get(sid)
    return {"text": card.render(s), "fields": _fields(s), "elapsed_s": s.elapsed_s()}


@router.delete("/api/session/{sid}", status_code=204)
async def delete_session(sid: str) -> Response:
    SESSIONS.pop(sid, None)
    return Response(status_code=204)


@router.get("/api/audio/{name}", response_model=None)
async def get_audio(name: str) -> Response:
    m = re.fullmatch(r"([0-9a-f]{64})\.wav", name)
    if not m:
        raise HTTPException(404)
    eph = tts.get_ephemeral(m.group(1))
    if eph is not None:  # read-back audio: user data, never cached by the browser or proxies
        return Response(eph, media_type="audio/wav", headers={"Cache-Control": "no-store"})
    p = cache.wav_path(m.group(1))
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="audio/wav", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/api/metrics")
async def get_metrics() -> dict:
    return {**gnani_http.metrics.snapshot(), "active_sessions": len(SESSIONS)}

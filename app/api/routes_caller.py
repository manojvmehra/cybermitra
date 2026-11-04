import logging
import re
import time

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app import audio, cache
from app.api.events import bus
from app.api.schemas import ConfirmIn, CreateSession, NumpadIn, PromptOut, SkipIn, SmsIn, TurnResponse
from app.config import get_settings
from app.dialog import packet as P
from app.dialog import prompts
from app.dialog.models import Action, Event, Session
from app.dialog.state_machine import next_state
from app.gnani import http as gnani_http
from app.gnani import stt, tts
from app.gnani.http import GnaniError
from app.logging_utils import log
from app.nlp import extractor
from app.queue.store import store
from app.ratelimit import limiter
from app.security import client_ip

logger = logging.getLogger("api")
router = APIRouter()

SESSIONS: dict[str, Session] = {}
MAX_UPLOAD_BYTES = 6 * 1024 * 1024
_SID = re.compile(r"[0-9a-f]{32}")
ASK_STATES = {"ASK_MORE_TXN": "more_txn", "REVIEW": "review", "DUP_CHECK": "dup_utr"}


def _sweep() -> None:
    ttl = get_settings().SESSION_TTL_S
    now = time.time()
    for sid in [k for k, v in SESSIONS.items() if now - v.last_active > ttl]:
        SESSIONS.pop(sid, None)
    store.sweep(now)


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


def live_view(s: Session) -> dict:
    """Fields as the operator's live tile and the caller's panel show them."""
    return {
        "channel": s.channel,
        "txns": [{"index": i, **{k: P.field_row(f) for k, f in t.fields.items()}} for i, t in enumerate(s.txns)],
        "fields": {k: P.field_row(f) for k, f in s.fields.items()},
    }


def _push_packets(s: Session, acts: list[Action]) -> None:
    """A PushPacket action puts the call's packet in the operator queue (no operator action needed)."""
    for a in acts:
        if a.type != "PushPacket" or s.packet_id:
            continue
        p = P.build(s, a.data["status"], a.data.get("reason"))
        s.packet_id = p.id
        moved = store.add(p)
        log(logger, "packet pushed", packet=p.id, status=p.status, reason=p.handoff_reason or "",
            n_txns=len(p.txns))
        bus.publish("packet_created", {"id": p.id, "status": p.status, "handoff_reason": p.handoff_reason,
                                       "session": s.id[:8]})
        if moved:
            bus.publish("queue_reordered", {"changes": [e.model_dump() for e in moved]})


def commit(s: Session, acts: list[Action]) -> dict:
    """Everything a finished turn does on any channel: queue a packet, keep the session, update the operator."""
    _push_packets(s, acts)
    SESSIONS[s.id] = s
    view = live_view(s)
    bus.publish("live_fields", {"session": s.id[:8], "state": s.state, "current_field": s.current_field,
                                "current_txn": s.current_txn, "elapsed_s": s.elapsed_s(), **view})
    log(logger, "turn", session=s.id[:8], state=s.state, field=s.current_field or "", n_actions=len(acts))
    return view


async def process_wav(s: Session, wav: bytes) -> tuple[Session, list[Action], str | None, str | None]:
    """One spoken turn: STT, then the FSM. -> (session, actions, transcript, error). Audio is not kept."""
    settings = get_settings()
    if audio.duration_s(wav) > settings.MAX_CLIP_S:
        return s, [Action(type="SpeakPrompt", text=prompts.text("TOO_LONG", s.lang, s.channel))], None, "too_long"
    s = s.model_copy()
    s.api_turns += 1  # every STT call counts toward the per-call cap, even silent clips
    SESSIONS[s.id] = s
    profile = stt.SttProfile.from_settings(s.lang)
    try:
        res = await stt.transcribe(wav, profile=profile, context=s.last_prompt_text or None,
                                   request_id=f"{s.id}-{s.api_turns}", use_cache=settings.STT_CACHE_LIVE)
    except GnaniError as e:
        log(logger, "stt failed", code=e.code, status=e.status)
        return s, [Action(type="SpeakPrompt", text=prompts.text("DIDNT_CATCH", s.lang, s.channel))], None, f"stt_{e.code}"
    if res.truncated:
        return s, [Action(type="SpeakPrompt", text=prompts.text("TOO_LONG", s.lang, s.channel))], None, "truncated"
    candidates = None
    if s.state == "NARRATIVE" and settings.EVON_MODE != "off":
        cands = await extractor.extract_narrative(res)
        candidates = {k: c.__dict__ for k, c in cands.items()}
    ev = Event(type="AUDIO_TURN", text=res.text, literal=res.literal, candidates=candidates)
    s, acts = next_state(s, ev)
    return s, acts, s.transcripts[-1] if s.transcripts else res.text, None


async def _respond(s: Session, acts: list[Action], transcript: str | None = None,
                   error: str | None = None) -> TurnResponse:
    view = commit(s, acts)
    rb = next((a.data for a in reversed(acts) if a.type == "ShowReadback"), None)
    if s.state != "READBACK":
        rb = None
    numpad = next((a.data for a in reversed(acts) if a.type == "ShowNumpad"), None)
    ask = ASK_STATES.get(s.state) or ("called_bank" if s.state == "GAP_FILL" and s.current_field == "called_bank"
                                      else None)
    done = s.state == "QUEUED" or s.state.startswith("HANDOFF")
    return TurnResponse(
        session_id=s.id, state=s.state, current_field=s.current_field, current_txn=s.current_txn, ask=ask,
        transcript=transcript, txns=view["txns"], fields=view["fields"], readback=rb, numpad=numpad,
        prompt=await _render_prompts(s, acts), handoff=s.handoff, packet_id=s.packet_id,
        summary=P.victim_summary(s, s.packet_id) if done else None,
        elapsed_s=s.elapsed_s(), demo_banner=_banner(), error=error, can_back=bool(s.history) and not done,
    )


@router.get("/health")
async def health() -> dict:
    s = get_settings()
    return {"ok": True, "gnani_key_present": bool(s.GNANI_API_KEY), "evon_mode": s.EVON_MODE,
            "ffmpeg": audio.ffmpeg_available(), "app_name": s.APP_NAME,
            "operator_enabled": bool(s.OPERATOR_TOKEN), "telephony_enabled": s.TWILIO_ENABLED}


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
    if s.api_turns >= settings.MAX_TURNS_PER_CALL:
        # STT budget for this call is spent: hand it to a person (warm, with what we have) and stop
        if not s.handoff and s.state != "QUEUED":
            s, acts = next_state(s, Event(type="HUMAN", text="max_turns"))
            await _respond(s, acts)
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
    s, acts, transcript, error = await process_wav(s, wav)
    return await _respond(s, acts, transcript=transcript, error=error)


@router.post("/api/session/{sid}/sms")
async def sms(sid: str, body: SmsIn) -> TurnResponse:
    s, acts = next_state(_get(sid), Event(type="SMS_PASTED", text=body.text))
    return await _respond(s, acts)


@router.post("/api/session/{sid}/confirm")
async def confirm(sid: str, body: ConfirmIn) -> TurnResponse:
    s, acts = next_state(_get(sid), Event(type="BUTTON", field=body.field, txn_index=body.txn_index,
                                          chunk_index=body.chunk_index, answer=body.answer))
    return await _respond(s, acts)


@router.post("/api/session/{sid}/numpad")
async def numpad(sid: str, body: NumpadIn) -> TurnResponse:
    s, acts = next_state(_get(sid), Event(type="NUMPAD", field=body.field, txn_index=body.txn_index,
                                          digits=body.digits))
    return await _respond(s, acts)


@router.post("/api/session/{sid}/skip")
async def skip(sid: str, body: SkipIn) -> TurnResponse:
    s, acts = next_state(_get(sid), Event(type="SKIP", field=body.field, txn_index=body.txn_index))
    return await _respond(s, acts)


@router.post("/api/session/{sid}/back")
async def back(sid: str) -> TurnResponse:
    """Undo the last answer and ask that question again."""
    s, acts = next_state(_get(sid), Event(type="BACK"))
    return await _respond(s, acts)


@router.post("/api/session/{sid}/human")
async def human(sid: str) -> TurnResponse:
    """The caller pressed "Talk to a person": warm handoff with everything captured so far."""
    s, acts = next_state(_get(sid), Event(type="HUMAN"))
    return await _respond(s, acts)


@router.get("/api/session/{sid}/summary")
async def summary(sid: str) -> dict:
    s = _get(sid)
    return {**P.victim_summary(s, s.packet_id), "state": s.state, "elapsed_s": s.elapsed_s()}


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
    """Aggregate numbers only: no fields, no transcripts."""
    return {**store.metrics(), "gnani": gnani_http.metrics.snapshot(), "active_sessions": len(SESSIONS)}

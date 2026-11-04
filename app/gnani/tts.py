"""Gnani Timbre TTS (REST /api/v1/tts/inference)."""

import secrets
import time
from typing import Literal

from app import cache
from app.config import get_settings
from app.gnani import http

Lang = Literal["ta-IN", "en-IN"]


def voice_for(lang: Lang) -> str:
    s = get_settings()
    return s.TTS_VOICE_TA if lang == "ta-IN" else s.TTS_VOICE_EN


# 8 kHz µ-law with no file header, which is what a Twilio media stream plays
TELEPHONY_AUDIO = {"sample_rate": 8000, "num_channels": 1, "sample_width": 1, "encoding": "pcm_mulaw",
                   "container": "mulaw"}


def tts_key(text: str, lang: Lang, speed: float, voice: str | None = None, telephony: bool = False) -> str:
    s = get_settings()
    params: dict[str, object] = {"voice": voice or voice_for(lang), "model": s.TTS_MODEL, "lang": lang,
                                 "speed": speed, "sr": s.TTS_SAMPLE_RATE}
    if telephony:
        params |= {"sr": 8000, "container": "mulaw"}
    return cache.cache_key(text, params)


def audio_url(key: str) -> str:
    return f"/api/audio/{key}.wav"


# Read-back audio speaks the user's own digits. It must not land on disk, and its URL must not be derivable
# from the text (a content hash would let anyone test "was 98765 43210 read back?"). So: random token,
# memory only, short TTL.
_EPHEMERAL: dict[str, tuple[bytes, float]] = {}
_EPHEMERAL_BY_CONTENT: dict[str, str] = {}


def _sweep_ephemeral(now: float) -> None:
    for tok in [t for t, (_, exp) in _EPHEMERAL.items() if exp < now]:
        _EPHEMERAL.pop(tok, None)
    for ck in [c for c, t in _EPHEMERAL_BY_CONTENT.items() if t not in _EPHEMERAL]:
        _EPHEMERAL_BY_CONTENT.pop(ck, None)


def get_ephemeral(token: str) -> bytes | None:
    _sweep_ephemeral(time.time())
    hit = _EPHEMERAL.get(token)
    return hit[0] if hit else None


async def synthesize(text: str, *, lang: Lang, speed: float, request_id: str | None = None,
                     voice: str | None = None, persist: bool = True, telephony: bool = False) -> tuple[bytes, str]:
    """Returns (audio bytes, key): WAV, or raw 8 kHz µ-law with telephony=True. persist=True: disk cache keyed by content hash (static prompts).
    persist=False: in-memory only, keyed by a random token (anything containing user data)."""
    s = get_settings()
    key = tts_key(text, lang, speed, voice, telephony)
    now = time.time()
    if persist:
        hit = cache.get_wav(key)
    else:
        _sweep_ephemeral(now)
        tok = _EPHEMERAL_BY_CONTENT.get(key)
        hit = _EPHEMERAL[tok][0] if tok and tok in _EPHEMERAL else None
    if hit is not None:
        http.metrics.cache_hits += 1
        return hit, (key if persist else tok)  # type: ignore[return-value]
    http.metrics.cache_misses += 1
    body = {
        "text": text,
        "voice": voice or voice_for(lang),
        "model": s.TTS_MODEL,
        "language": lang,
        "speed": speed,
        "audio_config": TELEPHONY_AUDIO if telephony else {
            "sample_rate": s.TTS_SAMPLE_RATE, "num_channels": 1, "sample_width": 2,
            "encoding": "linear_pcm", "container": "wav"},
    }
    data, _ = await http.call("POST", "/api/v1/tts/inference", json=body, expect="bytes",
                              request_id=request_id, endpoint="tts")
    if persist:
        cache.put_wav(key, data)
        return data, key
    tok = secrets.token_hex(32)
    if len(_EPHEMERAL) >= 2000:  # bound memory: drop the oldest-expiring entry
        _EPHEMERAL.pop(min(_EPHEMERAL, key=lambda t: _EPHEMERAL[t][1]), None)
    _EPHEMERAL[tok] = (data, now + s.EPHEMERAL_AUDIO_TTL_S)
    _EPHEMERAL_BY_CONTENT[key] = tok
    return data, tok

"""Gnani Prisma STT (REST /stt/v3)."""

import json
import logging
import unicodedata
from dataclasses import asdict, dataclass, field, replace
from typing import Literal

from app import cache
from app.config import get_settings
from app.gnani import http

logger = logging.getLogger("gnani.stt")

DEFAULT_BIAS = ["SBI", "HDFC", "ICICI", "Axis", "Canara", "Indian", "IOB", "Kotak", "PhonePe", "GPay",
                "Paytm", "UPI", "UTR", "OTP", "KYC", "IMPS", "NEFT"]


@dataclass
class SttResult:
    text: str
    literal: str | None
    model: str
    detected_language: str | None
    truncated: bool
    latency_ms: int
    cached: bool
    request_id: str | None = None


@dataclass
class SttProfile:
    model: Literal["v2.5", "v3.0"] = "v2.5"
    language: str = "ta-IN"
    format: str = "transcribe"
    bias_score: float = 1.0
    topic: str | None = None
    keyterms: list[str] = field(default_factory=list)

    @classmethod
    def from_settings(cls, ui_lang: str = "ta") -> "SttProfile":
        """The session's UI language picks the STT language: Tamil UI -> STT_LANGUAGE, English UI -> STT_LANGUAGE_EN."""
        s = get_settings()
        language = s.STT_LANGUAGE_EN if ui_lang == "en" else s.STT_LANGUAGE
        return cls(model=s.STT_MODEL, language=language, format=s.STT_FORMAT,
                   bias_score=s.STT_BIAS_SCORE, topic=s.STT_V3_TOPIC)


def _letters_only(w: str) -> bool:
    # Tamil vowel signs / virama are combining marks (M*), which count as part of a letter-only word.
    return bool(w) and unicodedata.category(w[0])[0] == "L" and all(
        unicodedata.category(c)[0] in ("L", "M") for c in w)


def clean_bias_list(words: list[str]) -> list[str]:
    """v2.5 bias_list: ≤100 single letter-only words. API silently ignores invalid lists, so we filter."""
    kept: list[str] = []
    dropped: list[str] = []
    for w in words:
        (kept if _letters_only(w) else dropped).append(w)
    if dropped:
        logger.warning("dropped invalid bias_list entries", extra={"extra_fields": {"n": len(dropped)}})
    seen: set[str] = set()
    out = [w for w in kept if not (w in seen or seen.add(w))]  # type: ignore[func-returns-value]
    return out[:100]


def build_form(profile: SttProfile, bias_words: list[str] | None, context: str | None) -> dict[str, str]:
    data: dict[str, str] = {"language_code": profile.language, "format": profile.format}
    if profile.model == "v3.0":
        data["model"] = "prisma-v3.0"
        terms = (profile.keyterms or []) + (bias_words or [])
        if terms:
            data["keyterms"] = json.dumps(terms[:200], ensure_ascii=False)
        if profile.topic:
            data["topic"] = profile.topic[:1600]
        if context:
            data["previous_text"] = context[-600:]
    else:
        if "," in profile.language:
            raise ValueError("Prisma v2.5 accepts a single language_code")
        if profile.format not in ("verbatim", "transcribe"):
            raise ValueError("Prisma v2.5 supports only verbatim|transcribe")
        if profile.bias_score > 0:
            from app.nlp.lexicon_ta import BANK_ALIASES_TA_SCRIPT

            words = clean_bias_list(DEFAULT_BIAS + BANK_ALIASES_TA_SCRIPT + (bias_words or []))
            data["bias_list"] = json.dumps(words, ensure_ascii=False)
            data["bias_score"] = str(profile.bias_score)
    return data


def join_results(parts: list[SttResult]) -> SttResult:
    """One turn cut into pieces reads as one result. A piece with no literal leaves the turn without one,
    so the digit pipeline treats it as low confidence rather than comparing against a partial transcript."""
    if len(parts) == 1:
        return parts[0]
    literals = [p.literal for p in parts]
    return replace(
        parts[0],
        text=" ".join(p.text for p in parts if p.text.strip()),
        literal=None if None in literals else " ".join(x for x in literals if x and x.strip()),
        detected_language=next((p.detected_language for p in parts if p.detected_language), None),
        truncated=any(p.truncated for p in parts),
        latency_ms=sum(p.latency_ms for p in parts),
        cached=all(p.cached for p in parts),
    )


async def transcribe(
    wav_bytes: bytes,
    *,
    profile: SttProfile | None = None,
    bias_words: list[str] | None = None,
    context: str | None = None,
    request_id: str | None = None,
    use_cache: bool = True,
) -> SttResult:
    """use_cache=False for live user audio: nothing is read from or written to disk."""
    profile = profile or SttProfile.from_settings()
    form = build_form(profile, bias_words, context)
    key = cache.cache_key(wav_bytes, {"endpoint": "stt/v3", **form})
    hit = cache.get_json("stt", key) if use_cache else None
    if hit is not None:
        http.metrics.cache_hits += 1
        hit["cached"] = True
        return SttResult(**hit)
    http.metrics.cache_misses += 1

    body, latency = await http.call(
        "POST", "/stt/v3",
        files={"audio_file": ("audio.wav", wav_bytes, "audio/wav")},
        data=form, expect="json", request_id=request_id, endpoint="stt",
    )
    if body.get("success") is False:
        err = body.get("error") or {}
        raise http.GnaniError(200, str(err.get("type", "UNKNOWN")), str(err.get("message", "")), request_id)
    output = body.get("output") or {}
    result = SttResult(
        text=body.get("transcript") or "",
        literal=output.get("literal") if isinstance(output, dict) else None,
        model=body.get("model") or ("prisma-v3.0" if profile.model == "v3.0" else "prisma-v2.5"),
        detected_language=body.get("detected_language_code"),
        truncated=bool(body.get("truncated", False)),
        latency_ms=latency,
        cached=False,
        request_id=body.get("request_id"),
    )
    # Don't cache truncated results: the caller should retry with shorter audio.
    if use_cache and not result.truncated:
        cache.put_json("stt", key, asdict(result))
    return result

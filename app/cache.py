"""SHA-256 keyed disk cache. JSON for STT results, WAV for TTS audio."""

import hashlib
import json
from pathlib import Path
from typing import Any

from app.config import get_settings


def cache_key(payload: bytes | str, params: dict[str, Any]) -> str:
    h = hashlib.sha256()
    h.update(payload.encode("utf-8") if isinstance(payload, str) else payload)
    h.update(b"\x00")
    h.update(json.dumps(params, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return h.hexdigest()


def _dir(kind: str) -> Path:
    d = Path(get_settings().CACHE_DIR) / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_json(kind: str, key: str) -> dict[str, Any] | None:
    p = _dir(kind) / f"{key}.json"
    if not p.exists():
        return None
    data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    return data


def put_json(kind: str, key: str, value: dict[str, Any]) -> None:
    p = _dir(kind) / f"{key}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def wav_path(key: str) -> Path:
    return _dir("tts") / f"{key}.wav"


def get_wav(key: str) -> bytes | None:
    p = wav_path(key)
    return p.read_bytes() if p.exists() else None


def put_wav(key: str, data: bytes) -> None:
    p = wav_path(key)
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(p)

import asyncio
import base64
import hashlib
import re
import subprocess
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import audio
from app.gnani import http as gnani_http
from app.gnani import tts
from app.main import create_app
from app.ratelimit import limiter
from tests.test_api import BASE, stt_ok, tone_wav


@pytest.fixture
def client():
    limiter.reset()
    with TestClient(create_app()) as c:
        yield c
    gnani_http._client = None


@pytest.fixture
def mock_gnani():
    with respx.mock(assert_all_called=False) as r:
        r.post(f"{BASE}/api/v1/tts/inference").mock(return_value=httpx.Response(200, content=tone_wav(0.1)))
        yield r


def new_session(client, lang="en"):
    return client.post("/api/session", json={"lang": lang, "consent": True}).json()["session_id"]


# ---------------------------------------------------------------- headers
def test_security_headers_and_csp_hash(client):
    r = client.get("/")
    csp = r.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp and "'unsafe-inline'" not in \
        csp.split("script-src")[1].split(";")[0]
    # the HTML parser normalises CRLF to LF before the browser hashes an inline script
    html = r.content.decode("utf-8").replace("\r\n", "\n")
    script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    assert f"'sha256-{digest}'" in csp  # the inline script is allowed by hash, nothing else is
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "microphone=(self)" in r.headers["permissions-policy"]


def test_session_responses_not_cached(client, mock_gnani):
    r = client.post("/api/session", json={"lang": "en", "consent": True})
    assert r.headers["cache-control"] == "no-store"


def test_docs_disabled_by_default(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


# ---------------------------------------------------------------- request limits
def test_json_body_too_large(client, mock_gnani):
    sid = new_session(client)
    r = client.post(f"/api/session/{sid}/sms", content=b'{"text":"' + b"a" * 20000 + b'"}',
                    headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_chunked_body_too_large_without_content_length(client, mock_gnani):
    sid = new_session(client)

    def gen():
        for _ in range(40):
            yield b"x" * 1024

    r = client.post(f"/api/session/{sid}/sms", content=gen(), headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_audio_body_too_large(client, mock_gnani):
    sid = new_session(client)
    big = b"\0" * (8 * 1024 * 1024)
    r = client.post(f"/api/session/{sid}/turn", files={"audio": ("a.wav", big, "audio/wav")})
    assert r.status_code == 413


def test_uploads_never_spool_to_disk():
    from starlette.formparsers import MultiPartParser

    from app.security import MAX_AUDIO_BODY

    assert MultiPartParser.max_file_size >= MAX_AUDIO_BODY


def test_strict_schemas(client, mock_gnani):
    sid = new_session(client)
    assert client.post(f"/api/session/{sid}/skip", json={"field": "__class__"}).status_code == 422
    assert client.post(f"/api/session/{sid}/confirm",
                       json={"field": "amount", "chunk_index": -1, "answer": "yes"}).status_code == 422
    assert client.post(f"/api/session/{sid}/numpad", json={"field": "utr", "digits": ""}).status_code == 422
    assert client.post(f"/api/session/{sid}/sms", json={"text": ""}).status_code == 422


def test_malformed_session_id(client):
    assert client.get("/api/session/../../etc/summary").status_code == 404
    assert client.get("/api/session/" + "z" * 32 + "/summary").status_code == 404


def test_silent_clips_count_toward_turn_cap(client, mock_gnani, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MAX_TURNS_PER_CALL", "2")
    monkeypatch.setenv("SILENCE_HANDOFF_COUNT", "5")
    get_settings.cache_clear()
    route = mock_gnani.post(f"{BASE}/stt/v3").mock(return_value=stt_ok(""))
    sid = new_session(client)
    for _ in range(2):
        client.post(f"/api/session/{sid}/turn", files={"audio": ("a.wav", tone_wav(0.5), "audio/wav")})
    r = client.post(f"/api/session/{sid}/turn", files={"audio": ("a.wav", tone_wav(0.5), "audio/wav")})
    assert r.status_code == 429 and route.call_count == 2
    from app.api import routes_caller
    assert routes_caller.SESSIONS[sid].handoff_reason == "max_turns"  # warm handoff, not a dead end


def test_max_active_sessions(client, mock_gnani, monkeypatch):
    from app.api import routes_caller
    from app.config import get_settings

    monkeypatch.setenv("MAX_ACTIVE_SESSIONS", "1")
    get_settings.cache_clear()
    routes_caller.SESSIONS.clear()
    assert client.post("/api/session", json={"lang": "en", "consent": True}).status_code == 200
    r = client.post("/api/session", json={"lang": "en", "consent": True})
    assert r.status_code == 429 and r.json()["error"] == "server_busy"
    routes_caller.SESSIONS.clear()


def test_forwarded_for_ignored_unless_trusted(client, mock_gnani, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("PER_IP_SESSIONS_PER_HOUR", "1")
    get_settings.cache_clear()
    limiter.reset()
    h1, h2 = {"x-forwarded-for": "1.1.1.1"}, {"x-forwarded-for": "2.2.2.2"}
    body = {"lang": "en", "consent": True}
    assert client.post("/api/session", json=body, headers=h1).status_code == 200
    assert client.post("/api/session", json=body, headers=h2).status_code == 429  # spoofed header ignored
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    get_settings.cache_clear()
    limiter.reset()
    assert client.post("/api/session", json=body, headers=h1).status_code == 200
    assert client.post("/api/session", json=body, headers=h2).status_code == 200


# ---------------------------------------------------------------- PII at rest
def test_live_stt_and_readback_audio_never_touch_disk(client, mock_gnani):
    from app.config import get_settings

    mock_gnani.post(f"{BASE}/stt/v3").mock(return_value=stt_ok("andha number 98765 43218 la irundhu call"))
    sid = new_session(client)
    client.post(f"/api/session/{sid}/turn", files={"audio": ("a.wav", tone_wav(), "audio/wav")})
    cache_dir = Path(get_settings().CACHE_DIR)
    assert not (cache_dir / "stt").exists() or not any((cache_dir / "stt").iterdir())
    for f in ("amount", "datetime", "utr"):  # get to the phone read-back
        client.post(f"/api/session/{sid}/skip", json={"field": f, "txn_index": 0})
    for f in ("more_txn", "victim_bank", "payment_mode"):
        j = client.post(f"/api/session/{sid}/skip", json={"field": f}).json()
    assert j["state"] == "READBACK" and j["readback"]["field"] == "suspect_phone"
    # the read-back audio (speaks the digits) is served from memory with no-store
    url = j["prompt"]["audio_urls"][-1]
    token = url.rsplit("/", 1)[1][:-4]
    assert not (cache_dir / "tts" / f"{token}.wav").exists()
    r = client.get(url)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    # and its URL is random, not a hash of the text
    assert token not in {tts.tts_key(t, "en-IN", s) for t in [j["prompt"]["text"]] for s in (0.9, 1.0)}


def test_static_prompt_audio_is_cached_on_disk(client, mock_gnani):
    from app.config import get_settings

    j = client.post("/api/session", json={"lang": "en", "consent": True}).json()
    key = j["prompt"]["audio_url"].rsplit("/", 1)[1][:-4]
    assert (Path(get_settings().CACHE_DIR) / "tts" / f"{key}.wav").exists()


def test_english_session_uses_english_stt(client, mock_gnani):
    route = mock_gnani.post(f"{BASE}/stt/v3").mock(return_value=stt_ok("fifty thousand rupees lost"))
    sid = new_session(client, "en")
    client.post(f"/api/session/{sid}/turn", files={"audio": ("a.wav", tone_wav(), "audio/wav")})
    assert b"en-IN" in route.calls[0].request.content
    sid = new_session(client, "ta")
    client.post(f"/api/session/{sid}/turn", files={"audio": ("a.wav", tone_wav(), "audio/wav")})
    assert b"ta-IN" in route.calls[1].request.content


# ---------------------------------------------------------------- ffmpeg
async def test_ffmpeg_playlist_cannot_read_local_files(tmp_path):
    secret = tmp_path / "secret.wav"
    secret.write_bytes(tone_wav(1.0))
    playlist = f"#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1.0,\nfile:{secret.as_posix()}\n#EXT-X-ENDLIST\n"
    with pytest.raises(audio.AudioError):
        await audio.normalize(playlist.encode())
    concat = f"ffconcat version 1.0\nfile '{secret.as_posix()}'\n"
    with pytest.raises(audio.AudioError):
        await audio.normalize(concat.encode())


async def test_ffmpeg_hardening_flags(monkeypatch):
    seen = {}
    real = subprocess.run

    def spy(cmd, **kw):
        seen["cmd"] = cmd
        return real(cmd, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    await audio.normalize(tone_wav(0.3))
    a = list(seen["cmd"])
    assert a[a.index("-protocol_whitelist") + 1] == "pipe"
    assert a.index("-protocol_whitelist") < a.index("-i")
    assert "-t" in a and "-nostdin" in a


def test_ffmpeg_works_on_selector_event_loop():
    """uvicorn --reload on Windows uses a selector loop, where asyncio subprocesses raise NotImplementedError."""
    loop = asyncio.SelectorEventLoop()
    try:
        out = loop.run_until_complete(audio.normalize(tone_wav(0.3)))
    finally:
        loop.close()
    assert audio.duration_s(out) > 0.2


async def test_ffmpeg_caps_decoded_duration():
    out = await audio.normalize(tone_wav(40.0), max_s=5)
    assert audio.duration_s(out) <= 6.05

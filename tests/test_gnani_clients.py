import json

import httpx
import pytest
import respx

from app.gnani import http, stt, tts
from app.gnani.http import GnaniError, parse_error

BASE = "https://api.vachana.ai"
OK_V25 = {"success": True, "request_id": "r1", "transcript": "50000 ரூபாய்", "model": "prisma-v2.5",
          "processing_time": 0.4, "end_to_end_latency": 0.5, "output": {"literal": "ஐம்பதாயிரம் ரூபாய்"}}


@pytest.fixture(autouse=True)
async def _close_client():
    yield
    await http.aclose()


@respx.mock
async def test_stt_v25_dual_channel_and_cache():
    route = respx.post(f"{BASE}/stt/v3").mock(return_value=httpx.Response(200, json=OK_V25))
    prof = stt.SttProfile(model="v2.5", language="ta-IN", format="transcribe")
    r = await stt.transcribe(b"RIFF-fake", profile=prof)
    assert r.text == "50000 ரூபாய்" and r.literal == "ஐம்பதாயிரம் ரூபாய்" and not r.cached
    r2 = await stt.transcribe(b"RIFF-fake", profile=prof)
    assert r2.cached and route.call_count == 1  # cache hit never hits the network
    sent = route.calls[0].request
    assert sent.headers["X-API-Key-ID"] == "test-key"
    body = sent.content.decode("utf-8", errors="ignore")
    assert 'name="language_code"' in body and "transcribe" in body and 'name="model"' not in body
    assert 'name="bias_list"' in body and 'name="bias_score"' in body


@respx.mock
async def test_stt_v3_params():
    route = respx.post(f"{BASE}/stt/v3").mock(return_value=httpx.Response(200, json={
        "success": True, "transcript": "hi", "model": "prisma-v3.0", "detected_language_code": "ta-IN"}))
    prof = stt.SttProfile(model="v3.0", language="ta-IN,en-IN", format="codemix", topic="fraud",
                          keyterms=["UTR"])
    r = await stt.transcribe(b"x", profile=prof, context="How much money was lost?")
    assert r.detected_language == "ta-IN" and r.literal is None
    body = route.calls[0].request.content.decode("utf-8", errors="ignore")
    for f in ("prisma-v3.0", 'name="keyterms"', 'name="topic"', 'name="previous_text"'):
        assert f in body
    assert 'name="bias_list"' not in body


def test_v25_rejects_multilang():
    with pytest.raises(ValueError):
        stt.build_form(stt.SttProfile(model="v2.5", language="ta-IN,en-IN"), None, None)
    with pytest.raises(ValueError):
        stt.build_form(stt.SttProfile(model="v2.5", format="codemix"), None, None)


def test_bias_list_letters_only():
    out = stt.clean_bias_list(["SBI", "HDFC1", "two words", "எஸ்பிஐ", "Phone-Pe", "SBI"])
    assert out == ["SBI", "எஸ்பிஐ"]


@respx.mock
async def test_retry_429_then_200():
    route = respx.post(f"{BASE}/stt/v3").mock(side_effect=[
        httpx.Response(429, json={"detail": {"error_code": "RATE_LIMITED",
                                             "message": "Only 1 active request is allowed at a time.",
                                             "status_code": 429}}),
        httpx.Response(200, json=OK_V25)])
    r = await stt.transcribe(b"a", profile=stt.SttProfile())
    assert r.text and route.call_count == 2


@respx.mock
async def test_retry_504_then_200():
    route = respx.post(f"{BASE}/stt/v3").mock(side_effect=[
        httpx.Response(504, json={"error": "timeout", "code": "UPSTREAM_TIMEOUT", "message": "slow"}),
        httpx.Response(200, json=OK_V25)])
    await stt.transcribe(b"b", profile=stt.SttProfile())
    assert route.call_count == 2


@respx.mock
async def test_401_not_retried():
    route = respx.post(f"{BASE}/stt/v3").mock(return_value=httpx.Response(401, json={
        "detail": {"error_code": "INVALID_API_KEY", "message": "bad", "status_code": 401}}))
    with pytest.raises(GnaniError) as ei:
        await stt.transcribe(b"c", profile=stt.SttProfile())
    assert ei.value.code == "INVALID_API_KEY" and route.call_count == 1


@respx.mock
async def test_gives_up_after_4():
    route = respx.post(f"{BASE}/stt/v3").mock(return_value=httpx.Response(503, json={
        "success": False, "error": {"type": "UNAVAILABLE", "message": "x"}}))
    with pytest.raises(GnaniError):
        await stt.transcribe(b"d", profile=stt.SttProfile())
    assert route.call_count == 4


@respx.mock
async def test_transport_error_retried():
    route = respx.post(f"{BASE}/stt/v3").mock(side_effect=[httpx.ConnectError("boom"),
                                                            httpx.Response(200, json=OK_V25)])
    await stt.transcribe(b"e", profile=stt.SttProfile())
    assert route.call_count == 2


@respx.mock
async def test_empty_transcript_ok():
    respx.post(f"{BASE}/stt/v3").mock(return_value=httpx.Response(200, json={"success": True,
                                                                             "request_id": "x", "transcript": ""}))
    r = await stt.transcribe(b"f", profile=stt.SttProfile())
    assert r.text == ""


@respx.mock
async def test_truncated_not_cached():
    route = respx.post(f"{BASE}/stt/v3").mock(return_value=httpx.Response(200, json={
        "success": True, "transcript": "partial", "model": "prisma-v3.0", "truncated": True}))
    prof = stt.SttProfile(model="v3.0", language="ta-IN")
    r = await stt.transcribe(b"g", profile=prof)
    assert r.truncated
    await stt.transcribe(b"g", profile=prof)
    assert route.call_count == 2


def test_parse_error_shapes():
    assert parse_error(httpx.Response(400, json={"success": False, "error": {"type": "INVALID_FORMAT",
                                                                              "message": "m"}})) == ("INVALID_FORMAT", "m")
    assert parse_error(httpx.Response(422, json={"detail": [{"msg": "field required"}]}))[0] == "VALIDATION_ERROR"
    assert parse_error(httpx.Response(400, json={"success": False, "message": "bad voice",
                                                 "status_code": 400})) == ("HTTP_400", "bad voice")
    assert parse_error(httpx.Response(500, text="oops"))[0] == "HTTP_500"


@respx.mock
async def test_tts_body_and_cache():
    route = respx.post(f"{BASE}/api/v1/tts/inference").mock(return_value=httpx.Response(200, content=b"RIFFwav"))
    data, key = await tts.synthesize("சரியா?", lang="ta-IN", speed=0.9)
    assert data == b"RIFFwav" and len(key) == 64
    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "timbre-v2.5" and body["language"] == "ta-IN" and body["speed"] == 0.9
    assert body["voice"] == "Asmita" and body["audio_config"]["container"] == "wav"
    await tts.synthesize("சரியா?", lang="ta-IN", speed=0.9)
    assert route.call_count == 1
    assert tts.audio_url(key) == f"/api/audio/{key}.wav"


def test_metrics_snapshot():
    snap = http.metrics.snapshot()
    assert "cache_hit_rate" in snap and "latency_p95_ms" in snap

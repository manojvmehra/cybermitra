"""Experimental telephony: a fake Twilio on one side, mocked Gnani on the other. No network, no real call."""

import asyncio
import base64
import io
import json
import logging
import wave

import httpx
import numpy as np
import pytest
import respx
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from twilio.request_validator import RequestValidator

from app import audio
from app import twilio_bridge as B
from app.api import routes_caller
from app.config import get_settings
from app.dialog import packet as P
from app.dialog import prompts
from app.gnani import http as gnani_http
from app.main import create_app
from app.queue.store import store
from app.ratelimit import limiter
from tests.test_api import BASE, stt_ok

SID, TOKEN = "ACtest", "test-auth-token"
CALL = "CA0123456789abcdef"
FRAME = 160  # 20 ms
HOST = "abc.ngrok-free.app"
VOICE_URL = f"https://{HOST}/api/twilio/voice"
FORM = {"CallSid": CALL, "AccountSid": SID, "From": "+919000000001", "To": "+15005550006"}
HEADERS = {"host": HOST, "x-forwarded-proto": "https"}


def signature(params: dict, url: str = VOICE_URL, token: str = TOKEN) -> str:
    return RequestValidator(token).compute_signature(url, params)


def speech(ms: int = 600, amp: float = 8000) -> bytes:
    t = np.arange(ms * 8) / 8000
    return B.pcm_to_mulaw(amp * np.sin(2 * np.pi * 300 * t))


def quiet(ms: int) -> bytes:
    return B.pcm_to_mulaw(np.zeros(ms * 8))


def frames(data: bytes) -> list[bytes]:
    return [data[i:i + FRAME] for i in range(0, len(data), FRAME)]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("TWILIO_ENABLED", "true")
    get_settings.cache_clear()
    limiter.reset()
    routes_caller.SESSIONS.clear()
    store.reset()
    gnani_http._client = None
    with respx.mock(assert_all_called=False, base_url=BASE) as gnani, TestClient(create_app()) as c:
        gnani.post("/api/v1/tts/inference").mock(return_value=httpx.Response(200, content=b"\xff" * 400))
        c.gnani = gnani
        yield c
    gnani_http._client = None


def post_voice(c, form=None, sig=None, headers=None):
    form = form or FORM
    return c.post("/api/twilio/voice", data=form, headers={**(headers or HEADERS),
                                                           "X-Twilio-Signature": sig or signature(form)})


def stream_token(c) -> str:
    r = post_voice(c)
    assert r.status_code == 200
    return r.text.split('name="token" value="')[1].split('"')[0]


class FakeTwilio:
    """Plays Twilio's side of a media stream."""

    def __init__(self, ws, token: str, call=CALL):
        self.ws, self.played = ws, 0
        ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})
        ws.send_json({"event": "start", "streamSid": "MZ1", "start": {
            "accountSid": SID, "callSid": call, "streamSid": "MZ1", "tracks": ["inbound"],
            "customParameters": {"token": token},
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1}}})

    def wait_until_quiet(self) -> None:
        """Read the AI's audio up to its mark, then tell it the audio has finished playing."""
        while True:
            msg = self.ws.receive_json()
            if msg["event"] == "media":
                assert msg["streamSid"] == "MZ1"
                self.played += len(base64.b64decode(msg["media"]["payload"]))
            elif msg["event"] == "mark":
                self.ws.send_json({"event": "mark", "streamSid": "MZ1", "mark": {"name": msg["mark"]["name"]}})
                return

    def say(self) -> None:
        """A burst of speech then silence, which ends the turn."""
        for f in frames(speech() + quiet(B.END_SILENCE_MS + 100)):
            self.ws.send_json({"event": "media", "streamSid": "MZ1", "media": {
                "track": "inbound", "payload": base64.b64encode(f).decode()}})
        self.wait_until_quiet()

    def press(self, keys: str, reply: bool = True) -> None:
        for k in keys:
            self.ws.send_json({"event": "dtmf", "streamSid": "MZ1", "dtmf": {"track": "inbound", "digit": k}})
        if reply:
            self.wait_until_quiet()

    def hang_up(self) -> None:
        self.ws.send_json({"event": "stop", "streamSid": "MZ1", "stop": {"accountSid": SID, "callSid": CALL}})


def stt_script(c, *texts: str):
    c.gnani.post("/stt/v3").mock(side_effect=[stt_ok(t) for t in texts])


def packets():
    return list(store.packets.values())


STORY = "நேற்று எஸ்பிஐ பேங்க்ல இருந்து கால் வந்துச்சு ஓடிபி கேட்டாங்க ₹40,000 போச்சு"


def call_session():
    return next(s for s in routes_caller.SESSIONS.values() if s.channel == "phone")


# ---------------------------------------------------------------- µ-law
def test_decode_matches_the_g711_reference_values():
    assert B.mulaw_to_pcm(bytes([0xFF, 0x7F, 0x00, 0x80])).tolist() == [0, 0, -32124, 32124]


def test_decode_table_matches_python_audioop():
    audioop = pytest.importorskip("audioop")
    data = bytes(range(256))
    assert B.mulaw_to_pcm(data).tobytes() == audioop.ulaw2lin(data, 2)


def test_mulaw_round_trip_keeps_every_code():
    data = bytes(range(256))
    back = B.pcm_to_mulaw(B.mulaw_to_pcm(data))
    # 0x7F and 0xFF both mean silence, and silence encodes as 0xFF
    assert [a for a, b in zip(data, back, strict=True) if a != b] == [0x7F]


def test_mulaw_keeps_a_tone_clean():
    t = np.arange(8000) / 8000
    pcm = (10000 * np.sin(2 * np.pi * 440 * t)).astype(np.int16)
    out = B.mulaw_to_pcm(B.pcm_to_mulaw(pcm)).astype(np.float64)
    snr = 10 * np.log10(np.mean(pcm.astype(np.float64) ** 2) / np.mean((out - pcm) ** 2))
    assert snr > 30


def dominant_hz(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        x, rate = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16), w.getframerate()
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.fft.rfftfreq(len(x), 1 / rate)[int(np.argmax(spec))])


def test_inbound_audio_becomes_16k_wav_of_the_same_length_and_pitch():
    t = np.arange(8000) / 8000
    wav = B.mulaw8k_to_wav16k(B.pcm_to_mulaw(8000 * np.sin(2 * np.pi * 440 * t)))
    with wave.open(io.BytesIO(wav)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
    assert audio.duration_s(wav) == pytest.approx(1.0, abs=0.01)
    assert dominant_hz(wav) == pytest.approx(440, abs=3)


def test_wav_to_mulaw_and_back_round_trip():
    t = np.arange(24000) / 24000
    wav = audio.pcm_to_wav((8000 * np.sin(2 * np.pi * 1000 * t)).astype(np.int16).tobytes(), 24000)
    mu = B.wav_to_mulaw8k(wav)
    assert len(mu) == pytest.approx(8000, abs=2)
    assert dominant_hz(B.mulaw8k_to_wav16k(mu)) == pytest.approx(1000, abs=3)


def test_downsampling_blocks_frequencies_a_phone_cannot_carry():
    t = np.arange(24000) / 24000
    wav = audio.pcm_to_wav((8000 * np.sin(2 * np.pi * 7000 * t)).astype(np.int16).tobytes(), 24000)
    assert np.sqrt(np.mean(B.mulaw_to_pcm(B.wav_to_mulaw8k(wav)).astype(float) ** 2)) < 800


def test_wav_header_never_reaches_twilio():
    wav = audio.pcm_to_wav(np.zeros(800, dtype=np.int16).tobytes(), 16000)
    assert B.to_phone_audio(wav)[:4] != b"RIFF"
    assert B.to_phone_audio(b"\xff" * 10) == b"\xff" * 10


# ---------------------------------------------------------------- endpointing
def feed(ep: B.Endpointer, data: bytes) -> list[tuple[str, bytes | None]]:
    return [r for r in (ep.feed(f) for f in frames(data)) if r[0]]


def test_endpointer_finds_a_turn_after_silence():
    ep = B.Endpointer(25)
    out = feed(ep, quiet(500) + speech(800) + quiet(B.END_SILENCE_MS + 40))
    assert [k for k, _ in out] == ["speech"]
    assert len(out[0][1]) >= 800 * 8, "the turn keeps all the speech"


def test_endpointer_keeps_the_start_of_the_first_word():
    ep = B.Endpointer(25)
    _, turn = feed(ep, quiet(500) + speech(800) + quiet(B.END_SILENCE_MS + 40))[0]
    assert len(turn) >= (800 + B.PREROLL_MS - B.START_MS) * 8


def test_pause_between_digit_groups_does_not_end_the_turn():
    ep = B.Endpointer(25)
    out = feed(ep, speech(500) + quiet(B.END_SILENCE_MS - 200) + speech(500) + quiet(B.END_SILENCE_MS + 40))
    assert len(out) == 1 and len(out[0][1]) >= 1000 * 8


def test_a_click_is_not_a_turn():
    assert feed(B.Endpointer(25), quiet(200) + speech(60) + quiet(1000)) == []


def test_silence_times_out():
    assert [k for k, _ in feed(B.Endpointer(25), quiet(B.NO_SPEECH_MS + 40))] == ["no_speech"]


def test_a_long_turn_is_cut_at_the_clip_limit():
    out = feed(B.Endpointer(2), speech(3000))
    assert out[0][0] == "speech" and len(out[0][1]) <= (2000 + B.PREROLL_MS) * 8


def test_steady_line_noise_is_not_speech():
    rng = np.random.default_rng(0)
    noisy = B.pcm_to_mulaw(rng.normal(0, 120, 4000 * 8))
    assert feed(B.Endpointer(25), noisy) == []


# ---------------------------------------------------------------- mounting
def test_routes_absent_when_disabled():
    get_settings.cache_clear()
    assert get_settings().TWILIO_ENABLED is False
    with TestClient(create_app()) as c:
        assert c.post("/api/twilio/voice", data=FORM).status_code == 404
        with pytest.raises(WebSocketDisconnect), c.websocket_connect("/api/twilio/stream"):
            pass
        assert c.get("/health").json()["telephony_enabled"] is False


def test_routes_absent_without_an_auth_token(monkeypatch, caplog):
    monkeypatch.setenv("TWILIO_ENABLED", "true")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "")
    get_settings.cache_clear()
    with caplog.at_level(logging.WARNING), TestClient(create_app()) as c:
        assert c.post("/api/twilio/voice", data=FORM).status_code == 404
    assert "telephony is off" in caplog.text


# ---------------------------------------------------------------- webhook
def test_voice_answers_with_a_bidirectional_stream(client):
    r = post_voice(client)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/xml")
    assert f'<Stream url="wss://{HOST}/api/twilio/stream">' in r.text
    assert "?" not in r.text.split('url="')[1].split('"')[0], "Twilio rejects a query string on the stream URL"
    assert "<Record" not in r.text and "<Gather" not in r.text
    assert "1930" in r.text and "<Hangup/>" in r.text
    assert r.headers["cache-control"] == "no-store"


def test_missing_signature_rejected(client):
    r = client.post("/api/twilio/voice", data=FORM, headers=HEADERS)
    assert r.status_code == 403


def test_forged_signature_rejected(client):
    assert post_voice(client, sig=signature(FORM, token="not-the-token")).status_code == 403


def test_signature_for_changed_params_rejected(client):
    assert post_voice(client, form={**FORM, "CallSid": "CAother"}, sig=signature(FORM)).status_code == 403


def test_signature_for_another_url_rejected(client):
    assert post_voice(client, sig=signature(FORM, "https://evil.example/api/twilio/voice")).status_code == 403


def test_another_twilio_account_rejected(client):
    form = {**FORM, "AccountSid": "ACother"}
    assert post_voice(client, form=form).status_code == 403


def test_configured_public_url_is_what_gets_signed(client, monkeypatch):
    monkeypatch.setenv("TWILIO_PUBLIC_URL", "https://fixed.example.com/")
    get_settings.cache_clear()
    sig = signature(FORM, "https://fixed.example.com/api/twilio/voice")
    r = client.post("/api/twilio/voice", data=FORM, headers={"X-Twilio-Signature": sig})
    assert r.status_code == 200 and "wss://fixed.example.com/api/twilio/stream" in r.text


def test_rate_limited_caller_is_told_to_call_1930(client, monkeypatch):
    monkeypatch.setenv("PER_IP_SESSIONS_PER_HOUR", "1")
    get_settings.cache_clear()
    post_voice(client)
    r = post_voice(client)
    assert r.status_code == 200 and "1930" in r.text and "<Stream" not in r.text


# ---------------------------------------------------------------- stream auth
def rejected_stream(client, token: str, call: str = CALL) -> None:
    with client.websocket_connect("/api/twilio/stream") as ws:
        FakeTwilio(ws, token, call)
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
    assert e.value.code == 1008
    assert not routes_caller.SESSIONS, "no session, so no API credits, before the stream is authorised"


def test_stream_without_a_valid_token_is_closed(client):
    rejected_stream(client, "made-up")


def test_stream_token_is_bound_to_its_call(client):
    rejected_stream(client, stream_token(client), call="CAother")


def test_stream_token_works_only_once(client):
    tok = stream_token(client)
    with client.websocket_connect("/api/twilio/stream") as ws:
        tw = FakeTwilio(ws, tok)
        tw.wait_until_quiet()
        tw.hang_up()
    routes_caller.SESSIONS.clear()
    rejected_stream(client, tok)


def test_expired_stream_token_is_refused():
    from app.api import routes_twilio as R

    tok = R.issue_token(CALL, now=1000.0)
    assert R.redeem_token(tok, CALL, now=1000.0 + R.TOKEN_TTL_S + 1) is False


def test_stream_that_never_starts_is_closed(client):
    with client.websocket_connect("/api/twilio/stream") as ws:
        for _ in range(3):
            ws.send_json({"event": "connected"})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


# ---------------------------------------------------------------- the call
def run_call(client, body):
    with client.websocket_connect("/api/twilio/stream") as ws:
        tw = FakeTwilio(ws, stream_token(client))
        tw.wait_until_quiet()  # the opening
        body(tw)


ANSWERS = {"datetime": "நேத்து மத்தியானம் மூணு மணி", "utr": "430619827418", "victim_bank": "எஸ்பிஐ",
           "payment_mode": "UPI", "suspect_phone": "9876543218", "suspect_upi": "தெரியல", "suspect_bank": "தெரியல",
           "district": "மதுரை", "victim_name": "டெஸ்ட் குமார்", "victim_mobile": "9000000001"}


def test_scripted_call_reaches_the_review_queue(client):
    def prisma(_):
        s = next((x for x in routes_caller.SESSIONS.values() if x.channel == "phone"), None)
        return stt_ok(STORY if s.state == "NARRATIVE" else ANSWERS[s.current_field])

    client.gnani.post("/stt/v3").mock(side_effect=prisma)
    with client.websocket_connect("/api/twilio/stream") as ws:
        tw = FakeTwilio(ws, stream_token(client))
        tw.wait_until_quiet()
        assert tw.played > 0, "the opening was played"
        tw.say()
        for _ in range(60):
            s = call_session()
            if s.state in ("READBACK", "REVIEW"):
                tw.press("1")
            elif s.state == "ASK_MORE_TXN" or s.current_field == "called_bank":
                tw.press("2")
            elif s.state == "GAP_FILL":
                tw.say()
            else:
                break
        assert call_session().state == "QUEUED"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()  # the bridge closes the stream, and TwiML hangs up

    assert len(packets()) == 1
    p = packets()[0]
    assert p.status == "ready_for_review" and p.channel == "phone"
    assert p.txns[0]["amount"].value == 40000 and p.txns[0]["amount"].status == "confirmed"
    assert p.txns[0]["utr"].value == "430619827418" and p.txns[0]["utr"].status == "confirmed"
    assert p.txns[0]["utr"].source != "numpad", "spoken, then confirmed on the keypad"
    assert "experimental telephony" in P.render_text(p)
    assert "+919000000001" not in p.model_dump_json(), "the caller's number is not stored"


def test_operator_sees_the_phone_label(client, monkeypatch):
    monkeypatch.setenv("OPERATOR_TOKEN", "op")
    get_settings.cache_clear()
    stt_script(client, STORY)

    def body(tw):
        tw.say()
        tw.press("0")

    run_call(client, body)
    q = client.get("/api/operator/queue", headers={"X-Operator-Token": "op"}).json()
    assert q["handoffs"][0]["channel_label"] == "experimental telephony"


def test_key_0_hands_off_with_what_was_captured(client):
    stt_script(client, STORY)

    def body(tw):
        tw.say()
        tw.press("0")

    run_call(client, body)
    p = packets()[0]
    assert p.status == "needs_human" and p.handoff_reason == "caller_request"
    assert p.txns[0]["amount"].value == 40000


def test_key_3_replays_what_was_just_said(client):
    stt_script(client, STORY)

    def body(tw):
        tw.say()
        tw.played = 0
        tw.press("3")
        assert tw.played == 800, "the key help and question again, not the whole call"
        assert call_session().state == "READBACK", "repeating changes nothing"
        tw.hang_up()

    run_call(client, body)


def test_key_2_then_typing_a_correction(client):
    def prisma(_):
        s = call_session()
        return stt_ok("₹40,000 போச்சு" if s.state == "NARRATIVE" else ANSWERS.get(s.current_field, ""))

    client.gnani.post("/stt/v3").mock(side_effect=prisma)

    def body(tw):
        tw.say()
        tw.press("1")  # ✓ amount
        tw.say()  # time
        tw.press("1")
        tw.say()  # UTR, read back as 4306 1982 7418
        assert call_session().readback.field == "utr"
        tw.press("1")
        tw.press("1")
        tw.press("2")  # the last group is wrong
        assert call_session().readback.awaiting == "correct"
        tw.press("1299", reply=False)  # keys are digits now: 1 and 2 must not count as yes and no
        tw.press("#")  # typed digits are authoritative, so the call moves on without a read-back
        assert call_session().state == "ASK_MORE_TXN"
        tw.hang_up()

    run_call(client, body)
    f = packets()[0].txns[0]["utr"]
    assert f.value == "430619821299" and f.status == "confirmed" and f.source == "numpad"


def test_star_types_a_utr_and_hash_submits(client):
    def body(tw):
        tw.say()  # story
        tw.press("1")  # ✓ amount
        tw.say()  # time
        tw.press("1")
        assert call_session().current_field == "utr"
        tw.press("*")
        tw.press("430619827418", reply=False)
        tw.press("#")
        tw.hang_up()

    stt_script(client, "₹40,000 போச்சு", ANSWERS["datetime"])
    run_call(client, body)
    f = packets()[0].txns[0]["utr"]
    assert f.value == "430619827418" and f.source == "numpad" and f.status == "confirmed"


def test_digit_keys_mean_nothing_when_no_yes_or_no_is_asked(client):
    def body(tw):
        tw.press("1", reply=False)
        tw.press("2", reply=False)
        tw.press("9", reply=False)
        tw.hang_up()

    run_call(client, body)
    assert not packets()


def test_silence_twice_hands_off(client):
    def quiet_turn(tw):
        for f in frames(quiet(B.NO_SPEECH_MS + 40)):
            tw.ws.send_json({"event": "media", "media": {"track": "inbound", "payload": base64.b64encode(f).decode()}})
        tw.wait_until_quiet()

    def body(tw):
        quiet_turn(tw)
        quiet_turn(tw)

    run_call(client, body)
    p = packets()[0]
    assert p.status == "needs_human" and p.handoff_reason == "silence"


def test_hanging_up_mid_call_keeps_what_the_caller_said(client):
    stt_script(client, STORY)

    def body(tw):
        tw.say()
        tw.hang_up()

    run_call(client, body)
    p = packets()[0]
    assert p.status == "needs_human" and p.handoff_reason == "caller_hung_up"
    assert p.txns[0]["amount"].value == 40000


def test_hanging_up_before_saying_anything_leaves_nothing(client):
    run_call(client, lambda tw: tw.hang_up())
    assert not packets() and not routes_caller.SESSIONS


def test_caller_is_not_heard_while_the_ai_speaks(client):
    stt_script(client, STORY)
    with client.websocket_connect("/api/twilio/stream") as ws:
        tw = FakeTwilio(ws, stream_token(client))
        # the opening is still "playing": no mark sent back yet
        for f in frames(speech() + quiet(B.END_SILENCE_MS + 100)):
            ws.send_json({"event": "media", "media": {"track": "inbound", "payload": base64.b64encode(f).decode()}})
        tw.wait_until_quiet()
        tw.hang_up()
    assert not [c for c in client.gnani.calls if c.request.url.path == "/stt/v3"]


def test_a_step_with_nothing_to_say_keeps_listening_and_the_repeat_key(client):
    stt_script(client, STORY)

    async def go():
        sent = []

        async def send(x):
            sent.append(x)

        async def close():
            sent.append("closed")

        b = B.CallBridge(send, close, "en", "abc")
        b.last_audio = b"\xff" * 10
        await b._apply(b.s, [])
        assert b.last_audio == b"\xff" * 10 and b.listening and not sent

    asyncio.run(go())


def test_a_bug_in_the_call_closes_the_line_instead_of_leaving_it_silent(client, monkeypatch):
    def boom(*_):
        raise RuntimeError("bug")

    monkeypatch.setattr(routes_caller, "commit", boom)
    with client.websocket_connect("/api/twilio/stream") as ws:
        FakeTwilio(ws, stream_token(client))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_tts_failure_ends_the_call_safely(client):
    client.gnani.post("/api/v1/tts/inference").mock(return_value=httpx.Response(400, json={
        "success": False, "message": "bad", "status_code": 400}))
    with client.websocket_connect("/api/twilio/stream") as ws:
        FakeTwilio(ws, stream_token(client))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_otp_spoken_on_a_call_is_dropped(client):
    stt_script(client, "என் OTP 482913")

    def body(tw):
        tw.say()
        tw.hang_up()

    run_call(client, body)
    assert "482913" not in packets()[0].model_dump_json()


def test_caller_number_never_reaches_the_logs(client, caplog):
    stt_script(client, STORY)

    def body(tw):
        tw.say()
        tw.press("0")

    with caplog.at_level(logging.INFO):
        run_call(client, body)
    assert "9000000001" not in caplog.text and CALL not in caplog.text


def test_approve_makes_no_outbound_call(client, monkeypatch):
    monkeypatch.setenv("OPERATOR_TOKEN", "op")
    get_settings.cache_clear()
    stt_script(client, STORY)

    def body(tw):
        tw.say()
        tw.press("0")

    run_call(client, body)
    pid = packets()[0].id
    h = {"X-Operator-Token": "op"}
    before = sum(r.call_count for r in client.gnani.routes)
    client.post(f"/api/operator/packet/{pid}/claim", headers=h)
    assert client.post(f"/api/operator/packet/{pid}/approve", headers=h).status_code == 200
    assert sum(r.call_count for r in client.gnani.routes) == before


# ---------------------------------------------------------------- prompts
PHONE_IDS = [k for k in prompts.PROMPTS if k.startswith("PHONE_")]


@pytest.mark.parametrize("pid", PHONE_IDS)
def test_phone_prompts_exist_in_both_languages(pid):
    assert prompts.PROMPTS[pid]["ta"] and prompts.PROMPTS[pid]["en"]


@pytest.mark.parametrize("pid", PHONE_IDS)
def test_phone_prompts_never_mention_a_screen(pid):
    text = prompts.PROMPTS[pid]["en"].lower() + prompts.PROMPTS[pid]["ta"]
    for word in ("screen", "tap", "paste", "திரை", "பேஸ்ட்", "✓"):
        assert word not in text


@pytest.mark.parametrize("lang", ["ta", "en"])
def test_opening_says_experimental(lang):
    assert ("சோதனை" if lang == "ta" else "experimental") in prompts.text("OPENING", lang, "phone")


def test_web_prompts_unchanged():
    assert prompts.text("ASK_utr", "en") != prompts.text("ASK_utr", "en", "phone")
    assert "Paste" in prompts.text("ASK_utr", "en")


def test_json_message_garbage_is_ignored(client):
    with client.websocket_connect("/api/twilio/stream") as ws:
        tw = FakeTwilio(ws, stream_token(client))
        tw.wait_until_quiet()
        ws.send_text("not json")
        ws.send_text(json.dumps({"event": "media", "media": {"payload": "%%%"}}))
        ws.send_text(json.dumps({"event": "dtmf", "dtmf": {"digit": "x"}}))
        tw.hang_up()

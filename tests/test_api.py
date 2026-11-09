import io
import math
import re
import struct
import wave

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import audio
from app.gnani import http as gnani_http
from app.main import create_app
from app.ratelimit import limiter

BASE = "https://api.vachana.ai"


def tone_wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate)))
                               for i in range(int(seconds * rate))))
    return buf.getvalue()


@pytest.fixture
def client():
    limiter.reset()
    with TestClient(create_app()) as c:
        yield c
    gnani_http._client = None


SMS = ("Rs.50,000.00 debited from A/c XX1234 on 01-11-26 15:02 to VPA fraud.pay@ybl "
       "UPI Ref No 430619827418. -SBI")


def stt_ok(transcript: str, literal: str | None = None) -> httpx.Response:
    return httpx.Response(200, json={"success": True, "request_id": "r", "transcript": transcript,
                                     "model": "prisma-v2.5", "output": {"literal": literal or transcript}})


@pytest.fixture
def mock_gnani():
    with respx.mock(assert_all_called=False) as r:
        r.post(f"{BASE}/api/v1/tts/inference").mock(return_value=httpx.Response(200, content=tone_wav(0.1)))
        yield r


def test_health(client):
    j = client.get("/health").json()
    assert j["ok"] and j["gnani_key_present"] and j["evon_mode"] == "off"


def test_index(client):
    r = client.get("/")
    assert r.status_code == 200 and 'aria-label="Call 1930"' in r.text


def test_caller_page_is_a_phone_call(client):
    page = client.get("/").text
    assert 'id="startCall"' in page and 'id="endCall"' in page and 'id="dial"' in page
    assert "Tap to talk" not in page and "Hold to talk" not in page  # the line listens by itself, like a call
    assert "Yes / ஆம்" not in page and "No / இல்லை" not in page  # plain keys: the opening says what they do
    assert "tel:1930" not in page  # the caller is already on 1930


def test_back_undoes_an_answer_and_is_offered_only_when_possible(client):
    j = client.post("/api/session", json={"lang": "en", "consent": True}).json()
    sid = j["session_id"]
    assert j["can_back"] is False
    j = client.post(f"/api/session/{sid}/skip", json={"field": "amount"}).json()
    assert j["can_back"] is True and j["state"] == "GAP_FILL"
    j = client.post(f"/api/session/{sid}/back").json()
    assert j["state"] == "NARRATIVE" and j["can_back"] is False and j["prompt"]["text"] == "Tell me what happened."


def test_consent_required(client):
    assert client.post("/api/session", json={"lang": "en", "consent": False}).status_code == 400


def test_session_flow_sms_and_summary(client, mock_gnani):
    j = client.post("/api/session", json={"lang": "en", "consent": True}).json()
    sid = j["session_id"]
    assert j["state"] == "NARRATIVE" and j["prompt"]["audio_url"].startswith("/api/audio/")
    assert j["demo_banner"]
    audio_r = client.get(j["prompt"]["audio_url"])
    assert audio_r.status_code == 200 and audio_r.headers["content-type"] == "audio/wav"

    j = client.post(f"/api/session/{sid}/sms", json={
        "text": "Rs.50,000.00 debited from A/c XX1234 on 01-11-26 15:02 to VPA fraud.pay@ybl "
                "UPI Ref No 430619827418. -SBI"}).json()
    t = j["txns"][0]
    assert t["utr"]["source"] == "sms" and t["amount"]["display"] == "₹50,000"
    assert j["fields"]["victim_bank"]["value"] == "SBI"

    j = client.post(f"/api/session/{sid}/numpad", json={"field": "suspect_phone", "digits": "9876543218"}).json()
    assert j["fields"]["suspect_phone"]["status"] == "confirmed"

    summary = client.get(f"/api/session/{sid}/summary").json()
    assert summary["n_txns"] == 1 and summary["total_display"] == "₹50,000"
    assert [s["id"] for s in summary["next_steps"]][:2] == ["NS_CALL_BANK", "NS_KEEP_EVIDENCE"]
    assert client.delete(f"/api/session/{sid}").status_code == 204
    assert client.get(f"/api/session/{sid}/summary").status_code == 404


def test_turn_with_audio(client, mock_gnani):
    mock_gnani.post(f"{BASE}/stt/v3").mock(side_effect=[
        stt_ok("50,000 rupees pochu", "aimbadhaayiram rupees pochu"),
        stt_ok("yes"),
    ])
    sid = client.post("/api/session", json={"lang": "en", "consent": True}).json()["session_id"]
    j = client.post(f"/api/session/{sid}/turn", files={"audio": ("a.wav", tone_wav(), "audio/wav")}).json()
    assert j["state"] == "STORY_CHECK" and j["ask"] == "story"  # one check for what the story gave
    amt = j["txns"][0]["amount"]
    assert amt["value"] == 50000 and amt["confidence"] == "high" and amt["status"] == "pending"
    j = client.post(f"/api/session/{sid}/confirm", json={"field": "story", "answer": "yes"}).json()
    assert j["txns"][0]["amount"]["status"] == "confirmed"
    assert j["state"] == "GAP_FILL" and j["current_field"] == "datetime"
    j = client.post(f"/api/session/{sid}/skip", json={"field": "datetime", "txn_index": 0}).json()
    assert j["txns"][0]["datetime"]["status"] == "skipped" and j["state"] == "ASK_MORE_TXN"  # the UTR comes last
    m = client.get("/api/metrics").json()
    assert m["gnani"]["calls_by_endpoint"].get("stt", 0) >= 1


def test_turn_too_long(client, mock_gnani, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MAX_TURN_S", "30")
    get_settings.cache_clear()
    stt_route = mock_gnani.post(f"{BASE}/stt/v3").mock(return_value=stt_ok("x"))
    sid = client.post("/api/session", json={"lang": "en", "consent": True}).json()["session_id"]
    j = client.post(f"/api/session/{sid}/turn", files={"audio": ("a.wav", tone_wav(32), "audio/wav")}).json()
    assert j["error"] == "too_long" and stt_route.call_count == 0


def test_long_turn_is_split_and_joined(client, mock_gnani):
    stt_route = mock_gnani.post(f"{BASE}/stt/v3").mock(return_value=stt_ok("panam pochu"))
    sid = client.post("/api/session", json={"lang": "en", "consent": True}).json()["session_id"]
    j = client.post(f"/api/session/{sid}/turn", files={"audio": ("a.wav", tone_wav(60), "audio/wav")}).json()
    assert j["error"] is None and stt_route.call_count == 3
    assert j["transcript"].count("panam pochu") == 3


def test_split_cuts_in_the_pause():
    import numpy as np

    from app import audio

    rate = 16000
    tone = (8000 * np.sin(np.arange(rate * 40) / 8)).astype(np.int16)
    tone[rate * 22:rate * 23] = 0  # a pause inside the search zone before the 25 s limit
    pieces = audio.split_at_quiet(audio.pcm_to_wav(tone.tobytes(), rate), 25)
    lengths = [audio.duration_s(p) for p in pieces]
    assert len(pieces) == 2 and 22 <= lengths[0] <= 23 and abs(sum(lengths) - 40) < 0.01
    assert audio.split_at_quiet(pieces[1], 25) == [pieces[1]]


def test_turn_bad_audio(client, mock_gnani):
    sid = client.post("/api/session", json={"lang": "en", "consent": True}).json()["session_id"]
    j = client.post(f"/api/session/{sid}/turn", files={"audio": ("a.webm", b"not audio", "audio/webm")}).json()
    assert j["error"] == "audio_decode"


def test_turn_stt_error(client, mock_gnani):
    mock_gnani.post(f"{BASE}/stt/v3").mock(return_value=httpx.Response(402, json={
        "detail": {"error_code": "INSUFFICIENT_CREDIT", "message": "no credit", "status_code": 402}}))
    sid = client.post("/api/session", json={"lang": "en", "consent": True}).json()["session_id"]
    j = client.post(f"/api/session/{sid}/turn", files={"audio": ("a.wav", tone_wav(), "audio/wav")}).json()
    assert j["error"].startswith("stt_") and j["state"] == "NARRATIVE"


def test_tts_failure_still_returns_text(client):
    with respx.mock() as r:
        r.post(f"{BASE}/api/v1/tts/inference").mock(return_value=httpx.Response(400, json={
            "success": False, "message": "bad voice", "status_code": 400}))
        j = client.post("/api/session", json={"lang": "ta", "consent": True}).json()
    assert j["prompt"]["text"] and j["prompt"]["audio_url"] is None


def test_unknown_session(client):
    assert client.post("/api/session/nope/sms", json={"text": "x"}).status_code == 404


def test_audio_path_validation(client):
    assert client.get("/api/audio/../../etc.wav").status_code == 404
    assert client.get("/api/audio/" + "a" * 64 + ".wav").status_code == 404


def test_rate_limit(client, mock_gnani, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("PER_IP_SESSIONS_PER_HOUR", "1")
    get_settings.cache_clear()
    limiter.reset()
    assert client.post("/api/session", json={"lang": "en", "consent": True}).status_code == 200
    r = client.post("/api/session", json={"lang": "en", "consent": True})
    assert r.status_code == 429 and r.json()["call"] == "1930"


def test_human_button_warm_handoff(client, mock_gnani):
    sid = client.post("/api/session", json={"lang": "en", "consent": True}).json()["session_id"]
    j = client.post(f"/api/session/{sid}/sms", json={"text": SMS}).json()
    j = client.post(f"/api/session/{sid}/human").json()
    assert j["state"] == "HANDOFF_HUMAN" and j["packet_id"].startswith("CD-DRAFT-")
    assert j["summary"]["packet_id"] == j["packet_id"]
    assert "simulated" in j["prompt"]["text"]


async def test_normalize_roundtrip():
    out = await audio.normalize(tone_wav(0.5, rate=44100))
    assert abs(audio.duration_s(out) - 0.5) < 0.05
    parts = audio.split_wav(tone_wav(2.0), 0.75)
    assert len(parts) == 3


# ---------------------------------------------------------------- operator side
TOKEN = "op-test-token"
OP = {"X-Operator-Token": TOKEN}
SMS_2 = ("Rs.10,000.00 debited from A/c XX1234 on 01-11-26 15:09 to VPA fraud.pay@ybl "
         "UPI Ref No 430619827555. -SBI")


@pytest.fixture
def op(monkeypatch):
    from app.api.events import bus
    from app.config import get_settings
    from app.queue.store import store

    monkeypatch.setenv("OPERATOR_TOKEN", TOKEN)
    get_settings.cache_clear()
    store.reset()
    bus.sent.clear()
    yield
    store.reset()


def full_call(client, mock_gnani, handoff: bool = False) -> tuple[str, dict]:
    """A 2-transaction call driven entirely by the caller page (SMS + buttons + typed answers)."""
    j = client.post("/api/session", json={"lang": "ta", "consent": True}).json()
    sid = j["session_id"]
    j = client.post(f"/api/session/{sid}/sms", json={"text": SMS + "\n\n" + SMS_2}).json()
    assert len(j["txns"]) == 2
    if handoff:
        return sid, client.post(f"/api/session/{sid}/human").json()
    j = client.post(f"/api/session/{sid}/skip", json={"field": "amount"}).json()  # no story: straight to questions
    assert j["state"] == "ASK_MORE_TXN" and j["ask"] == "more_txn"
    j = client.post(f"/api/session/{sid}/confirm", json={"field": "more_txn", "answer": "no"}).json()
    for _ in range(30):
        if j["state"] == "QUEUED":
            break
        if j["ask"] == "called_bank":
            j = client.post(f"/api/session/{sid}/confirm", json={"field": "called_bank", "answer": "yes"}).json()
        elif j["current_field"] == "suspect_phone":
            j = client.post(f"/api/session/{sid}/numpad", json={"field": "suspect_phone", "digits": "9876543218"}).json()
        elif j["current_field"] == "district":
            j = client.post(f"/api/session/{sid}/numpad", json={"field": "district", "digits": "Madurai"}).json()
        else:
            j = client.post(f"/api/session/{sid}/skip", json={"field": j["current_field"]}).json()
    assert j["state"] == "QUEUED"  # no review question: the call ends with its summary
    return sid, j


def test_operator_token_required(client, op):
    assert client.get("/api/operator/queue").status_code == 401
    assert client.get("/api/operator/queue", headers={"X-Operator-Token": "wrong"}).status_code == 401
    assert client.get("/api/events").status_code == 401
    assert client.get("/api/operator/queue", headers=OP).status_code == 200


def test_operator_disabled_without_token(client, monkeypatch):
    monkeypatch.setenv("OPERATOR_TOKEN", "")  # empty beats a value in .env
    assert client.get("/api/operator/queue", headers={"X-Operator-Token": ""}).status_code == 503


def test_two_txn_call_reaches_queue_without_operator_action(client, mock_gnani, op):
    sid, j = full_call(client, mock_gnani)
    assert j["state"] == "QUEUED" and j["packet_id"].startswith("CD-DRAFT-")
    assert j["summary"]["n_txns"] == 2 and j["summary"]["total_display"] == "₹60,000"
    assert len(j["summary"]["next_steps"]) == 4
    q = client.get("/api/operator/queue", headers=OP).json()
    assert [i["id"] for i in q["review"]] == [j["packet_id"]] and not q["handoffs"]
    p = client.get(f"/api/operator/packet/{j['packet_id']}", headers=OP).json()
    assert p["status"] == "ready_for_review" and len(p["txns"]) == 2
    assert all(t[k]["source"] == "sms" for t in p["txns"] for k in ("amount", "utr", "datetime"))
    assert "Total         : ₹60,000 (2 transactions)" in p["text"] and "Handled by AI" in p["text"]
    assert "transcript" not in p  # transcripts go to the operator only on handoff
    from app.api.events import bus
    assert "packet_created" in bus.sent and "live_fields" in bus.sent


def test_every_number_in_packet_has_a_source(client, mock_gnani, op):
    _, j = full_call(client, mock_gnani)
    p = client.get(f"/api/operator/packet/{j['packet_id']}", headers=OP).json()
    rows = [f for t in p["txns"] for f in t.values()] + list(p["fields"].values())
    allowed = {"sms", "numpad", "operator", "both", "voice", "voice_itn", "voice_literal", "button", "evon"}
    assert all(r["source"] in allowed for r in rows if r["value"] is not None)


def test_handoff_needs_claim_before_approve(client, mock_gnani, op):
    sid, j = full_call(client, mock_gnani, handoff=True)
    pid = j["packet_id"]
    q = client.get("/api/operator/queue", headers=OP).json()
    assert [i["id"] for i in q["handoffs"]] == [pid] and q["handoffs"][0]["handoff_reason"] == "caller_request"
    p = client.get(f"/api/operator/packet/{pid}", headers=OP).json()
    assert p["status"] == "needs_human" and isinstance(p["transcript"], list)
    assert len(p["txns"]) == 2  # warm handoff: what the caller already gave travels with the call
    assert client.post(f"/api/operator/packet/{pid}/approve", headers=OP).status_code == 409
    assert client.post(f"/api/operator/packet/{pid}/edit", headers=OP,
                       json={"field": "district", "value": "Madurai"}).status_code == 409
    assert client.post(f"/api/operator/packet/{pid}/claim", headers=OP).json()["status"] == "claimed"
    s = client.get(f"/api/session/{sid}/summary").json()
    assert s["operator_claimed"] is True
    p = client.post(f"/api/operator/packet/{pid}/approve", headers=OP).json()
    assert p["status"] == "approved" and p["approval_latency_s"] is not None
    assert client.post(f"/api/operator/packet/{pid}/approve", headers=OP).status_code == 409


def test_operator_edit_validates_and_marks_source(client, mock_gnani, op):
    _, j = full_call(client, mock_gnani)
    pid = j["packet_id"]
    r = client.post(f"/api/operator/packet/{pid}/edit", headers=OP,
                    json={"field": "utr", "txn_index": 1, "value": "1234"})
    assert r.status_code == 422
    p = client.post(f"/api/operator/packet/{pid}/edit", headers=OP,
                    json={"field": "victim_mobile", "value": "+91 91234 56780"}).json()
    assert p["fields"]["victim_mobile"]["value"] == "9123456780"
    assert p["fields"]["victim_mobile"]["source"] == "operator"
    p = client.post(f"/api/operator/packet/{pid}/edit", headers=OP,
                    json={"field": "amount", "txn_index": 2, "value": "2500"}).json()
    assert len(p["txns"]) == 3 and p["total"] == 62500  # operator added a missed debit
    q = client.get("/api/operator/queue", headers=OP).json()
    assert any(a["event"] == "edit" and "victim_mobile" in a["reason"] for a in q["audit"])
    assert not any("9123456780" in a["reason"] for a in q["audit"])


def test_reject_needs_reason(client, mock_gnani, op):
    _, j = full_call(client, mock_gnani)
    pid = j["packet_id"]
    assert client.post(f"/api/operator/packet/{pid}/reject", headers=OP, json={"reason": ""}).status_code == 422
    p = client.post(f"/api/operator/packet/{pid}/reject", headers=OP, json={"reason": "test call"}).json()
    assert p["status"] == "rejected" and p["reject_reason"] == "test call"


def test_approve_makes_no_outbound_call(client, op):
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as r:
        r.post(f"{BASE}/api/v1/tts/inference").mock(return_value=httpx.Response(200, content=tone_wav(0.1)))
        _, j = full_call(client, None)
        before = len(r.calls)
        pid = j["packet_id"]
        client.get(f"/api/operator/packet/{pid}", headers=OP)
        p = client.post(f"/api/operator/packet/{pid}/approve", headers=OP).json()
        assert p["status"] == "approved"
        assert len(r.calls) == before  # approving touched no network at all


def test_live_fields_emitted_during_turn(client, mock_gnani, op):
    from app.api.events import bus

    mock_gnani.post(f"{BASE}/stt/v3").mock(return_value=stt_ok("50,000 rupees pochu"))
    sid = client.post("/api/session", json={"lang": "en", "consent": True}).json()["session_id"]
    bus.sent.clear()
    client.post(f"/api/session/{sid}/turn", files={"audio": ("a.wav", tone_wav(), "audio/wav")})
    assert bus.sent == ["live_fields"]
    q = client.get("/api/operator/queue", headers=OP).json()
    live = [x for x in q["live"] if x["session"] == sid[:8]]
    assert live and live[0]["txns"][0]["amount"]["value"] == 50000


async def test_sse_stream_format():
    from app.api.events import Broadcaster

    b = Broadcaster()
    gen = b.stream(max_events=1)
    assert await gen.__anext__() == ": connected\n\n"
    b.publish("live_fields", {"session": "abc", "x": "த"})
    out = await gen.__anext__()
    assert out.startswith("event: live_fields\ndata: ") and '"x": "த"' in out
    assert b.subscribers == 1
    await gen.aclose()
    assert b.subscribers == 0


def test_metrics_have_no_pii(client, mock_gnani, op):
    full_call(client, mock_gnani)
    full_call(client, mock_gnani, handoff=True)
    m = client.get("/api/metrics").json()
    assert m["calls_total"] == 2 and m["calls_handled_by_ai"] == 1 and m["containment_rate"] == 0.5
    assert m["handoffs_by_reason"] == {"caller_request": 1}
    body = str(m)
    assert "430619827418" not in body and "9876543218" not in body and "fraud.pay" not in body


def test_operator_page_served(client):
    r = client.get("/operator")
    assert r.status_code == 200 and "X-Operator-Token" in r.text
    # The only thing a page may keep in the browser is its theme: the operator token stays in memory.
    keys = re.findall(r"localStorage\.\w+\(\s*([^,)]+)", r.text)
    assert keys and set(keys) <= {'"cyberdesk-theme"', "THEME_KEY"}
    assert "sessionStorage" not in r.text and 'THEME_KEY = "cyberdesk-theme"' in r.text
    assert not [line for line in r.text.splitlines() if "localStorage" in line and "token" in line.lower()]


def test_pages_are_revalidated_on_every_load(client):
    for path in ("/", "/operator"):
        assert client.get(path).headers["cache-control"] == "no-cache"


def test_hanging_up_after_speaking_reaches_an_officer(client, mock_gnani):
    mock_gnani.post(f"{BASE}/stt/v3").mock(return_value=stt_ok("50,000 rupees pochu"))
    sid = client.post("/api/session", json={"lang": "en", "consent": True}).json()["session_id"]
    client.post(f"/api/session/{sid}/turn", files={"audio": ("a.wav", tone_wav(), "audio/wav")})
    assert client.post(f"/api/session/{sid}/hangup").status_code == 204
    s = client.get(f"/api/session/{sid}/summary").json()
    assert s["handoff"] == "HANDOFF_HUMAN"


def test_hanging_up_before_saying_anything_drops_the_call(client):
    sid = client.post("/api/session", json={"lang": "en", "consent": True}).json()["session_id"]
    assert client.post(f"/api/session/{sid}/hangup").status_code == 204
    assert client.get(f"/api/session/{sid}/summary").status_code == 404

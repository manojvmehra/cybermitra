import json
import logging
import re

from app.logging_utils import JsonFormatter, mask, mask_digits


def test_mask_digits():
    assert mask_digits("9876543210") == "98•••••210"
    assert mask_digits("430619827418") == "4306••••7418"


def test_mask_text():
    s = mask("call from 98765 43210, UTR 430619827418, Rs.50,000 to fraud.pay@ybl")
    assert not re.search(r"[6-9]\d{9}", s.replace(" ", ""))
    assert "430619827418" not in s and "50,000" not in s and "fraud.pay@" not in s
    assert "1930" in mask("call 1930")  # short numbers are left alone


def test_json_formatter_masks_extra_fields():
    rec = logging.LogRecord("x", logging.INFO, "", 0, "phone 9876543210", None, None)
    rec.extra_fields = {"transcript": "my number 9876543210"}  # type: ignore[attr-defined]
    out = json.loads(JsonFormatter().format(rec))
    assert "9876543210" not in json.dumps(out)


def test_full_session_leaves_no_pii_in_log_file(tmp_path):
    """DoD: run a session full of (fake) PII with file logging on, then scan the log like an auditor would."""
    import httpx
    import respx
    from fastapi.testclient import TestClient

    from app.gnani import http as gnani_http
    from app.main import create_app
    from app.ratelimit import limiter
    from scripts.check_logs_pii import main as scan
    from tests.test_api import BASE, stt_ok, tone_wav

    log_file = tmp_path / "logs" / "app.log"
    log_file.parent.mkdir()
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    old_level = root.level
    root.setLevel(logging.INFO)
    try:
        limiter.reset()
        with respx.mock(assert_all_called=False) as r, TestClient(create_app()) as c:
            r.post(f"{BASE}/api/v1/tts/inference").mock(return_value=httpx.Response(200, content=tone_wav(0.1)))
            r.post(f"{BASE}/stt/v3").mock(side_effect=[
                stt_ok("andha number 98765 43218 la irundhu call, 50,000 rupees pochu, UTR 430619827418"),
                httpx.Response(401, json={"detail": {"error_code": "INVALID_API_KEY", "message": "9876543218",
                                                     "status_code": 401}}),
            ])
            sid = c.post("/api/session", json={"lang": "en", "consent": True}).json()["session_id"]
            c.post(f"/api/session/{sid}/turn", files={"audio": ("a.wav", tone_wav(), "audio/wav")})
            c.post(f"/api/session/{sid}/turn", files={"audio": ("a.wav", tone_wav(), "audio/wav")})
            c.post(f"/api/session/{sid}/sms", json={"text": "Rs.50,000.00 debited A/c XX1234 to fraud.pay@ybl "
                                                             "UPI Ref No 430619827418"})
            c.post(f"/api/session/{sid}/numpad", json={"field": "victim_mobile", "digits": "9123456780"})
            c.post(f"/api/session/{sid}/numpad", json={"field": "victim_name", "digits": "Test Kumar"})
        gnani_http._client = None
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
        handler.close()
    assert log_file.read_text(encoding="utf-8").strip(), "expected some log lines"
    assert scan(str(log_file.parent)) == 0


def test_scanner_detects_unmasked_pii(tmp_path):
    from scripts.check_logs_pii import main as scan

    (tmp_path / "x.log").write_text('{"msg": "call from 9876543210"}\n', encoding="utf-8")
    assert scan(str(tmp_path)) == 1

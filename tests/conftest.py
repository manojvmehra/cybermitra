import os
import tempfile

import pytest

os.environ.setdefault("GNANI_API_KEY", "test-key")
os.environ["CACHE_DIR"] = tempfile.mkdtemp(prefix="cm-cache-")
os.environ["EVON_MODE"] = "off"
os.environ["DAILY_SESSION_CAP"] = "1000"
os.environ["PER_IP_SESSIONS_PER_HOUR"] = "1000"
# Tests never use the developer's real .env for telephony. test_twilio.py turns it on where it needs it.
os.environ["TWILIO_ENABLED"] = "false"
os.environ["TWILIO_ACCOUNT_SID"] = "ACtest"
os.environ["TWILIO_AUTH_TOKEN"] = "test-auth-token"
os.environ["TWILIO_PUBLIC_URL"] = ""


@pytest.fixture(autouse=True)
def _fresh_cache(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    from app.gnani import http

    monkeypatch.setattr(http, "_backoff", lambda attempt: 0)
    yield

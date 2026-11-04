"""The opening stays short: under 15 s spoken, measured on real Timbre audio on 2026-11-05."""

import pytest

from app.dialog import prompts

# Limits just above the measured versions: web ta 11.7 s, web en 10.6 s, phone ta 14.4 s, phone en 12.2 s.
MAX_CHARS = {("web", "en"): 175, ("web", "ta"): 175, ("phone", "en"): 235, ("phone", "ta"): 215}


@pytest.mark.parametrize(("channel", "lang"), list(MAX_CHARS))
def test_opening_is_short_and_ends_on_the_question(channel, lang):
    t = prompts.text("OPENING", lang, channel)
    assert len(t) <= MAX_CHARS[(channel, lang)]
    assert "1930" in t and "OTP" in t and t.count("1930") == 1
    assert t.endswith(("Tell me what happened.", "சொல்லுங்க."))

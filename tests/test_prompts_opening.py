"""The opening carries the keys (1 yes, 2 no, star to type, hash to submit) and one question for the whole story,
so it is longer than the 15 s first measured on real Timbre audio on 2026-11-05. It is spoken at Timbre speed 1.15
and the caller page plays it 1.3x faster. Re-measure with Timbre before quoting a duration."""

import pytest

from app.dialog import prompts

MAX_CHARS = {("web", "en"): 330, ("web", "ta"): 320, ("phone", "en"): 385, ("phone", "ta"): 370}


@pytest.mark.parametrize(("channel", "lang"), list(MAX_CHARS))
def test_opening_is_short_and_ends_on_the_question(channel, lang):
    t = prompts.text("OPENING", lang, channel)
    assert len(t) <= MAX_CHARS[(channel, lang)]
    assert t.count("1930") == 1 and "OTP" not in t  # the caller dialled 1930; no disclaimers
    assert t.endswith(("from which bank.", "சொல்லுங்க."))


@pytest.mark.parametrize("channel", ["web", "phone"])
def test_opening_explains_the_keys(channel):
    t = prompts.text("OPENING", "en", channel)
    assert "Press 1 for yes" in t and "2 for no" in t and "3 if you did not understand" in t
    assert "press star" in t and "hash" in t


@pytest.mark.parametrize("channel", ["web", "phone"])
def test_opening_asks_for_the_whole_story_at_once(channel):
    t = prompts.text("OPENING", "en", channel)
    for must in ("in one go", "what happened", "when", "how much", "UPI", "which bank"):
        assert must in t
    assert "UTR" not in t and "mobile" not in t  # typed later, at the end

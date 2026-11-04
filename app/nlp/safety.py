"""Safety checks: forbidden-PII detection (OTP/PIN/CVV/...), non-financial and wellbeing handoffs."""

import re
from dataclasses import dataclass
from typing import Literal

from app.nlp.numbers import find_number_spans, normalise_text, words

SECRET_CUES = ["otp", "ஓடிபி", "ஓ டி பி", "pin", "பின்", "cvv", "சிவிவி", "password", "பாஸ்வேர்ட்", "passcode",
               "mpin", "upi pin", "atm pin", "கடவுச்சொல்"]
ID_CUES = ["aadhaar", "aadhar", "ஆதார்", "pan card", "pan number", "பான் கார்டு", "account number",
           "அக்கவுண்ட் நம்பர்", "card number", "கார்டு நம்பர்"]
NONFIN_CUES = ["sextortion", "morphed", "morph", "nude", "naked", "photo leak", "video leak", "blackmail",
               "harass", "stalking", "நிர்வாண", "மார்ஃப்", "ஆபாச", "photo podren", "video podren",
               "photo poduven", "video poduven", "fake profile", "போட்டோ போடுவேன்", "வீடியோ போடுவேன்"]
SELF_HARM_CUES = ["suicide", "kill myself", "end my life", "want to die", "die pannidren", "saaganum",
                  "sethuduven", "sethupoiduven", "தற்கொலை", "சாகணும்", "செத்துடுவேன்", "செத்துப்போயிடுவேன்",
                  "உயிரை விட", "வாழ விருப்பம் இல்ல", "vaazha virupam illa", "uyira vida"]

Flag = Literal["SECRET", "ID", "NONFIN", "SELF_HARM"]


@dataclass
class SafetyResult:
    flags: list[Flag]
    scrubbed_text: str


def _has(t: str, cues: list[str]) -> bool:
    return any(normalise_text(c) in t for c in cues)


def _cue_starts(ws: list[str], cues: list[str]) -> list[int]:
    """Word index just after each cue occurrence (cues may be multi-word)."""
    out = []
    for c in cues:
        cw = normalise_text(c).split()
        for i in range(len(ws) - len(cw) + 1):
            if ws[i:i + len(cw)] == cw:
                out.append(i + len(cw))
    return out


def _secret_near(text: str, cues: list[str], min_len: int, max_len: int, window: int) -> bool:
    """A digit run of the given length starting within `window` words after a cue, that is not an amount.
    ("pin போட்டேன், ₹25,000 போச்சு" is a normal story, not a leaked PIN.)"""
    ws = words(text)
    after = _cue_starts(ws, cues)
    if not after:
        return False
    for sp in find_number_spans(text):
        if sp.has_currency or sp.has_mult or not (min_len <= len(sp.digits) <= max_len):
            continue
        if any(0 <= sp.start - a <= window for a in after):
            return True
    return False


def check(text: str) -> SafetyResult:
    t = normalise_text(text or "")
    flags: list[Flag] = []
    if _has(t, SELF_HARM_CUES):
        flags.append("SELF_HARM")
    if _has(t, NONFIN_CUES):
        flags.append("NONFIN")
    scrubbed = text or ""
    if _secret_near(text or "", SECRET_CUES, 4, 6, 4):
        flags.append("SECRET")
        scrubbed = "[removed: secret code]"
    if _secret_near(text or "", ID_CUES, 9, 16, 5):
        flags.append("ID")
        scrubbed = "[removed: ID / account number]"
    # a bare 16-digit card number is always dropped
    if re.search(r"(?<!\d)(?:\d[ -]?){16}(?!\d)", text or ""):
        flags.append("ID")
        scrubbed = "[removed: card number]"
    return SafetyResult(flags, scrubbed)

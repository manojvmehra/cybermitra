"""Yes / no / correction intent detection for read-back confirmation. Any "no" wins."""

import re
from dataclasses import dataclass
from typing import Literal

from app.nlp.numbers import normalise_text, parse_digit_string

Intent = Literal["YES", "NO", "CORRECTION", "DONT_KNOW", "REPEAT", "HUMAN", "UNKNOWN"]

YES = ["ஆமா", "ஆமாம்", "சரி", "சரிதான்", "ஹா", "ஆம்", "கரெக்ட்", "ok", "okay", "yes", "correct", "aama", "aamaa",
       "aamam", "sari", "seri", "saridhaan", "sarithaan", "haan", "ha", "yeah", "yep", "right", "crct", "ஓகே",
       # English answers as Prisma writes them in Tamil script
       "எஸ்", "யெஸ்", "ஓக்கே", "கரெக்ட்டு", "ரைட்", "சரியா இருக்கு", "correct thaan", "ama"]
NO = ["இல்ல", "இல்லை", "தப்பு", "வேண்டாம்", "இல்லே", "illa", "illai", "ille", "thappu", "tappu", "no", "wrong",
      "nope", "not", "vendam", "vendaam", "venam", "வேணாம்", "தவறு", "தப்பா",
      "நோ", "ராங்", "ராங்கு"]
DONT_KNOW = ["தெரியல", "தெரியாது", "theriyala", "theriyadhu", "theriyathu", "dont know", "don't know", "not sure",
             "no idea", "ஞாபகம் இல்ல", "nyabagam illa", "gnabagam illa", "skip", "next", "அடுத்தது", "adutthadhu",
             "தெரியலை", "ஞாபகம் இல்லை", "மறந்துட்டேன்", "marandhutten", "forgot", "ஸ்கிப்", "நெக்ஸ்ட்", "டோன்ட் நோ"]
REPEAT = ["திரும்ப", "மறுபடி", "thirumba", "marupadi", "again", "repeat", "enna", "என்ன", "pardon", "sorry",
          "ரிப்பீட்", "அகெய்ன்", "புரியல", "புரியலை", "puriyala", "once more", "one more time"]
HUMAN = ["ஆள் வேணும்", "aal venum", "officer", "human", "person", "agent", "ஆபிசர்", "அதிகாரி", "ஆபீசர்",
         "real person", "talk to someone"]
POS_LAST = ["கடைசி", "kadaisi", "last", "கடைசில", "kadaisila"]
POS_FIRST = ["முதல்", "முதல", "mudhal", "mudhala", "first", "starting", "ஆரம்பம்"]


@dataclass
class YesNo:
    intent: Intent
    digits: str | None = None
    position: Literal["first", "last"] | None = None


def _has(text: str, words: list[str]) -> bool:
    for w in words:
        wn = normalise_text(w)
        if " " in wn:
            if wn in text:
                return True
        elif re.search(rf"(?<![^\s]){re.escape(wn)}(?![^\s])", text):
            return True
    return False


def _has_prefix(text: str, words: list[str]) -> bool:
    # Tamil words often carry suffixes ("இல்லைங்க", "சரிங்க", "illainga")
    return any(re.search(rf"(?<![^\s]){re.escape(normalise_text(w))}", text) for w in words)


def classify(text: str) -> YesNo:
    t = re.sub(r"[,.]", " ", normalise_text(text or "")).strip()
    if not t:
        return YesNo("UNKNOWN")
    if _has(t, HUMAN):
        return YesNo("HUMAN")
    if _has(t, DONT_KNOW) or _has_prefix(t, ["தெரியல", "theriyala"]):
        return YesNo("DONT_KNOW")
    no = _has(t, NO) or _has_prefix(t, ["இல்ல", "illa", "thapp", "தப்ப"])
    yes = _has(t, YES) or _has_prefix(t, ["சரி", "ஆமா", "aama", "sari"])
    digits = parse_digit_string(t).value
    if no:
        if digits:
            pos: Literal["first", "last"] | None = None
            if _has_prefix(t, POS_LAST):
                pos = "last"
            elif _has_prefix(t, POS_FIRST):
                pos = "first"
            return YesNo("CORRECTION", str(digits), pos)
        return YesNo("NO")
    if yes:
        return YesNo("YES")
    if _has(t, REPEAT):
        return YesNo("REPEAT")
    if digits:
        # bare digits without yes/no: a correction attempt
        return YesNo("CORRECTION", str(digits), None)
    return YesNo("UNKNOWN")


def apply_correction(chunk: str, yn: YesNo) -> str | None:
    """Return the corrected chunk, or None if the position cannot be resolved (→ ask numpad)."""
    if yn.digits is None:
        return None
    d = yn.digits
    if len(d) == len(chunk):
        return d
    if yn.position == "last" and len(d) < len(chunk):
        return chunk[: len(chunk) - len(d)] + d
    if yn.position == "first" and len(d) < len(chunk):
        return d + chunk[len(d):]
    return None

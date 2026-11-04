"""Read-back chunking and digit-word rendering. We render digits as words ourselves so Timbre's
text normalisation cannot regroup ("98765 43210" -> 3-3-4) or compress ("double four")."""

from dataclasses import dataclass
from datetime import datetime

from app.dialog import prompts
from app.nlp import lexicon_ta as L


@dataclass
class ReadbackStep:
    field: str
    chunk_index: int
    total_chunks: int
    chunk_digits: str
    text: str
    audio_url: str | None = None
    txn_index: int | None = None


def chunk(field: str, value: str | int) -> list[str]:
    v = str(value)
    if field in ("suspect_phone", "victim_mobile") and len(v) == 10:
        return [v[:5], v[5:]]
    if field == "utr" and len(v) == 12:
        return [v[:4], v[4:8], v[8:]]
    if field == "suspect_upi" and "@" in v:
        local, handle = v.split("@", 1)
        return [local[i:i + 4] for i in range(0, len(local), 4)] + ["@" + handle]
    return [v]


def render_digits_ta(chunk_digits: str) -> str:
    return ", ".join(L.DIGIT_WORDS_TA[int(c)] for c in chunk_digits if c.isdigit())


def render_digits_en(chunk_digits: str) -> str:
    return ", ".join(L.DIGIT_WORDS_EN[int(c)] for c in chunk_digits if c.isdigit())


# ---- amounts as words (spaced combining forms; parse_amount(render_amount_ta(n)) == n)
_U_TA = ["", "ஒன்று", "இரண்டு", "மூன்று", "நான்கு", "ஐந்து", "ஆறு", "ஏழு", "எட்டு", "ஒன்பது"]
_U_TA_BEFORE_MULT = ["", "ஒரு", "இரண்டு", "மூன்று", "நான்கு", "ஐந்து", "ஆறு", "ஏழு", "எட்டு", "ஒன்பது"]
_TEEN_TA = ["பத்து", "பதினொன்று", "பன்னிரண்டு", "பதிமூன்று", "பதினான்கு", "பதினைந்து", "பதினாறு", "பதினேழு",
            "பதினெட்டு", "பத்தொன்பது"]
_TENS_TA = ["", "", "இருபது", "முப்பது", "நாற்பது", "ஐம்பது", "அறுபது", "எழுபது", "எண்பது", "தொண்ணூறு"]
_TENS_TA_C = ["", "", "இருபத்து", "முப்பத்து", "நாற்பத்து", "ஐம்பத்து", "அறுபத்து", "எழுபத்து", "எண்பத்து",
              "தொண்ணூற்று"]
_HUND_TA = ["", "நூறு", "இருநூறு", "முந்நூறு", "நானூறு", "ஐந்நூறு", "அறுநூறு", "எழுநூறு", "எண்ணூறு", "தொள்ளாயிரம்"]
_HUND_TA_C = ["", "நூற்று", "இருநூற்று", "முந்நூற்று", "நானூற்று", "ஐந்நூற்று", "அறுநூற்று", "எழுநூற்று",
              "எண்ணூற்று", "தொள்ளாயிரத்து"]


def _below100_ta(n: int, before_mult: bool) -> str:
    if n < 10:
        return (_U_TA_BEFORE_MULT if before_mult else _U_TA)[n]
    if n < 20:
        return _TEEN_TA[n - 10]
    t, u = divmod(n, 10)
    if u == 0:
        return _TENS_TA[t]
    return f"{_TENS_TA_C[t]} {(_U_TA_BEFORE_MULT if before_mult else _U_TA)[u]}"


def _below1000_ta(n: int, before_mult: bool) -> str:
    h, rest = divmod(n, 100)
    parts = []
    if h:
        parts.append(_HUND_TA_C[h] if rest else _HUND_TA[h])
    if rest:
        parts.append(_below100_ta(rest, before_mult))
    return " ".join(parts)


def render_amount_ta(n: int) -> str:
    parts: list[str] = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thou, n = divmod(n, 1000)
    if crore:
        parts.append(f"{_below1000_ta(crore, True)} {'கோடியே' if (lakh or thou or n) else 'கோடி'}")
    if lakh:
        parts.append(f"{_below100_ta(lakh, True)} {'லட்சத்து' if (thou or n) else 'லட்சம்'}")
    if thou:
        parts.append(f"{_below100_ta(thou, True)} {'ஆயிரத்து' if n else 'ஆயிரம்'}")
    if n:
        parts.append(_below1000_ta(n, False))
    return " ".join(parts) + " ரூபாய்"


_U_EN = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_T_EN = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _below1000_en(n: int) -> str:
    h, rest = divmod(n, 100)
    parts = []
    if h:
        parts.append(f"{_U_EN[h]} hundred")
    if rest:
        parts.append(_U_EN[rest] if rest < 20 else " ".join(x for x in [_T_EN[rest // 10], _U_EN[rest % 10]] if x))
    return " ".join(parts)


def render_amount_en(n: int) -> str:
    parts: list[str] = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thou, n = divmod(n, 1000)
    for v, w in ((crore, "crore"), (lakh, "lakh"), (thou, "thousand")):
        if v:
            parts.append(f"{_below1000_en(v)} {w}")
    if n:
        parts.append(_below1000_en(n))
    return " ".join(parts) + " rupees"


_MONTHS_EN = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September",
              "October", "November", "December"]


_POD_EN = {9: "morning", 13: "afternoon", 18: "evening", 21: "night"}
_POD_TA = {9: "காலை", 13: "மதியம்", 18: "சாயங்காலம்", 21: "இரவு"}


def with_precision(value: str, precision: str | None) -> str:
    """Read-back chunk for a datetime: 'dd-mm-yyyy HH:MM|precision' so the phrase matches what was said."""
    return f"{value}|{precision}" if precision else value


def render_datetime(value: str, lang: str, now: datetime | None = None) -> str:
    """'01-11-2026 15:30' -> 'நவம்பர் ஒன்று, மதியம் மூன்று மணி முப்பது நிமிடம்' / '1 November, 3:30 PM'.
    A '|day' or '|part_of_day' suffix reads only what is known ('yesterday, evening'). Today and yesterday
    are said as words. Anything not in that format (typed free text) is read as-is."""
    value, _, precision = value.partition("|")
    try:
        dt = datetime.strptime(value, "%d-%m-%Y %H:%M")
    except ValueError:
        return value
    now = now or datetime.now()
    rel = {0: ("today", "இன்னைக்கு"), 1: ("yesterday", "நேத்து")}.get((now.date() - dt.date()).days)
    h12 = dt.hour % 12 or 12
    if lang == "en":
        day = rel[0] if rel else f"{dt.day} {_MONTHS_EN[dt.month]}"
        if precision == "day":
            return day
        if precision == "part_of_day" and dt.minute == 0 and dt.hour in _POD_EN:
            return f"{day}, {_POD_EN[dt.hour]}"
        ampm = "AM" if dt.hour < 12 else "PM"
        t = f"{h12} {ampm}" if dt.minute == 0 else f"{h12}:{dt.minute:02d} {ampm}"
        return f"{day}, {t}"
    day_ta = rel[1] if rel else f"{L.MONTH_NAMES_TA[dt.month]} {_below100_ta(dt.day, False)}"
    if precision == "day":
        return day_ta
    if precision == "part_of_day" and dt.minute == 0 and dt.hour in _POD_TA:
        return f"{day_ta}, {_POD_TA[dt.hour]}"
    if 5 <= dt.hour < 12:
        tod = "காலை"
    elif 12 <= dt.hour < 16:
        tod = "மதியம்"
    elif 16 <= dt.hour < 19:
        tod = "சாயங்காலம்"
    else:
        tod = "இரவு"
    t = f"{tod} {_below100_ta(h12, False)} மணி"
    if dt.minute:
        t += f" {_below100_ta(dt.minute, False)} நிமிடம்"
    return f"{day_ta}, {t}"


def chunk_words(field: str, chunk_value: str, lang: str) -> str:
    if field == "datetime":
        return render_datetime(chunk_value, lang)
    if field == "called_bank":
        return {"yes": "ஆமா", "no": "இல்ல"}.get(chunk_value, chunk_value) if lang == "ta" else chunk_value
    if field == "amount":
        n = int(chunk_value)
        return render_amount_ta(n) if lang == "ta" else render_amount_en(n)
    if field in ("utr", "suspect_phone", "victim_mobile"):
        return render_digits_ta(chunk_value) if lang == "ta" else render_digits_en(chunk_value)
    if field == "suspect_upi":
        if chunk_value.startswith("@"):
            return ("அட், " if lang == "ta" else "at, ") + ", ".join(chunk_value[1:])
        return ", ".join(render_digits_ta(c) if c.isdigit() and lang == "ta" else
                         render_digits_en(c) if c.isdigit() else c for c in chunk_value)
    return chunk_value


def step(field: str, chunks: list[str], index: int, lang: str, txn_index: int | None = None,
         n_txns: int = 1) -> ReadbackStep:
    c = chunks[index]
    words = chunk_words(field, c, lang)
    lbl = prompts.label(field, lang)
    if len(chunks) > 1:
        # ordinals as words, never "1/2" (TTS may read it as "half")
        ord_ta = ["முதல் பகுதி", "இரண்டாம் பகுதி", "மூன்றாம் பகுதி", "நான்காம் பகுதி", "ஐந்தாம் பகுதி"]
        ord_en = ["first part", "second part", "third part", "fourth part", "fifth part"]
        k = min(index, 4)
        lbl = f"{lbl}, {ord_ta[k] if lang == 'ta' else ord_en[k]}"
    txt = prompts.text("READBACK", lang, label=lbl, words=words)
    if txn_index is not None and n_txns > 1:
        txt = prompts.text("TXN_PREFIX", lang, n=txn_index + 1) + txt
    return ReadbackStep(field, index, len(chunks), c, txt, txn_index=txn_index)

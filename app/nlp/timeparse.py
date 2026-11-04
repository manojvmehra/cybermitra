"""Spoken time of a debit -> an estimate with a precision. Deterministic; the result is always read back.

Handles relative times (12 நிமிஷம் முன்னாடி / arai mani nerathukku munnadi / rendu mani neram aachu / just now),
day words (இன்னைக்கு / nethu / mundhaanethu / N naal munnadi), explicit dates (நவம்பர் 2), clock times
(3:30, pathu mani, moonarai mani) and part-of-day words (kaalaila 09:00, madhiyam 13:00, saayangaalam 18:00,
raathiri 21:00). Already-formatted ITN/SMS datetimes pass straight through.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal

from app.nlp import lexicon_ta as L
from app.nlp import numbers as N

Precision = Literal["minute", "hour", "part_of_day", "day"]
FMT = "%d-%m-%Y %H:%M"

PART_OF_DAY_HOUR = {"morning": 9, "afternoon": 13, "evening": 18, "night": 21}
JUST_NOW_OFFSET_MIN = 5


@dataclass
class TimeResult:
    value: datetime | None
    precision: Precision | None = None
    method: str = ""
    warnings: list[str] = field(default_factory=list)

    def formatted(self) -> str | None:
        return self.value.strftime(FMT) if self.value else None


def contains(text_norm: str, phrase: str) -> bool:
    """Phrase match on normalised text. Short ASCII cues must be whole words ("am" is not in "amount")."""
    p = N.normalise_text(phrase)
    if p.isascii() and len(p) <= 4:
        return f" {p} " in f" {text_norm} "
    return p in text_norm


def cue_positions(ws: list[str], cues: list[str]) -> list[int]:
    pos = []
    norm_cues = [N.normalise_text(c).split() for c in cues]
    for i in range(len(ws)):
        for cw in norm_cues:
            if cw and ws[i:i + len(cw)] == cw:
                pos.append(i)
    return pos


def _span_number(sp: N.Span) -> float | None:
    """A small spoken number in a span, including halves ("மூணரை" -> 3.5, "அரை" -> 0.5)."""
    frac = sum(t.value for t in sp.tokens if t.kind == "FRAC")
    whole = int(sp.digits) if sp.digits.isdigit() else 0
    if not sp.digits and not frac:
        return None
    return whole + frac


def _clock(text: str, ws: list[str]) -> tuple[int, int, bool] | None:
    """-> (hour, minute, minute_given)."""
    m = re.search(r"(?<!\d)([01]?\d|2[0-3])[:.]([0-5]\d)(?!\d)", text)
    if m:
        return int(m.group(1)), int(m.group(2)), True
    mani = cue_positions(ws, L.MANI_CUES)
    for sp in N.find_number_spans(text):
        if any(sp.start <= p <= sp.end + 1 for p in mani):
            v = _span_number(sp)
            if v is not None and 0 <= v < 24:
                minute = int(round((v - int(v)) * 60))
                return int(v), minute, minute != 0
    return None


def _explicit_date(text: str, ws: list[str], now: datetime) -> date | None:
    """'நவம்பர் 2' / '2 November' / '2nd nov' -> that date (this year, or last year if it would be future)."""
    for month, names in L.MONTHS.items():
        pos = cue_positions(ws, names)
        if not pos:
            continue
        for sp in N.find_number_spans(text):
            if any(abs(sp.start - p) <= 2 for p in pos) and sp.digits.isdigit() and 1 <= int(sp.digits) <= 31:
                for year in (now.year, now.year - 1):
                    try:
                        d = date(year, month, int(sp.digits))
                    except ValueError:
                        break
                    if d <= now.date():
                        return d
    return None


def _passthrough(text: str) -> TimeResult | None:
    s = text.strip()
    for fmt, prec in ((FMT, "minute"), ("%d-%m-%Y", "day"), ("%d/%m/%Y %H:%M", "minute"), ("%d/%m/%Y", "day")):
        try:
            return TimeResult(datetime.strptime(s, fmt), prec, "itn_digits")  # type: ignore[arg-type]
        except ValueError:
            continue
    return None


def _ago(minutes: float, now: datetime, precision: Precision, method: str) -> TimeResult:
    return TimeResult((now - timedelta(minutes=minutes)).replace(second=0, microsecond=0), precision, method)


def parse_time(s: str, now: datetime | None = None) -> TimeResult:
    now = now or datetime.now()
    if not s or not s.strip():
        return TimeResult(None)
    res = _passthrough(s) or _parse(s, now)
    if res.value is not None and res.value > now + timedelta(minutes=1):
        return TimeResult(None, None, res.method, ["future"])
    return res


def _parse(text: str, now: datetime) -> TimeResult:
    t = N.normalise_text(text)
    ws = N.words(text)
    method = "tamil_words" if re.search(r"[஀-௿]", text) else "roman_words"

    def has(cues: list[str]) -> bool:
        return any(contains(t, c) for c in cues)

    if has(L.TOMORROW_CUES) and not has(L.DAYS_AGO_CUES):
        return TimeResult(None, None, method, ["future"])
    if has(L.JUST_NOW_CUES):
        return _ago(JUST_NOW_OFFSET_MIN, now, "minute", method)
    for cues, unit, prec in ((L.HOURS_AGO_CUES, 60, "hour"), (L.MINUTES_AGO_CUES, 1, "minute")):
        if has(cues):
            for sp in N.find_number_spans(text):
                n = _span_number(sp)
                if n:
                    # "half an hour" / "1.5 hours" are minute-precise; whole hours are hour-precise
                    p = "minute" if unit == 1 or n != int(n) else prec
                    return _ago(n * unit, now, p, method)  # type: ignore[arg-type]
            if has(["அரை", "arai", "half"]):
                return _ago(0.5 * unit, now, "minute", method)

    day: date | None = None
    if has(L.DAY_BEFORE_CUES):
        day = (now - timedelta(days=2)).date()
    elif has(L.DATE_CUES["yesterday"]):
        day = (now - timedelta(days=1)).date()
    elif has(L.DATE_CUES["today"]):
        day = now.date()
    if day is None and has(L.DAYS_AGO_CUES):
        for sp in N.find_number_spans(text):
            n = _span_number(sp)
            if n is not None and 0 < n <= 60:
                day = (now - timedelta(days=int(n))).date()
                break
    if day is None:
        day = _explicit_date(text, ws, now)

    tod = next((k for k, cues in L.TIME_OF_DAY.items() if has(cues)), None)
    clock = _clock(text, ws)

    if clock is None:
        if tod is None:
            if day is None:
                return TimeResult(None)
            return TimeResult(datetime(day.year, day.month, day.day, 12, 0), "day", method)
        hour = PART_OF_DAY_HOUR[tod]
        base = day or now.date()
        dt = datetime(base.year, base.month, base.day, hour, 0)
        if day is None and dt > now:  # latest past: "raathiri" said at 10 am is last night
            dt -= timedelta(days=1)
        return TimeResult(dt, "part_of_day", method)

    hour, minute, minute_given = clock
    if tod is not None:
        if hour < 12 and (tod in ("afternoon", "evening") or (tod == "night" and hour >= 6)):
            hour += 12
        elif tod == "night" and hour == 12:
            hour = 0
        base = day or now.date()
        dt = datetime(base.year, base.month, base.day, hour, minute)
        if day is None and dt > now:
            dt -= timedelta(days=1)
    elif day is not None and day < now.date():
        # a past day with no am/pm word: 1–6 o'clock is how people say the afternoon
        dt = datetime(day.year, day.month, day.day, hour + 12 if 1 <= hour <= 6 else hour, minute)
    else:
        # today / no day: the latest past time that matches the clock reading
        base = day or now.date()
        cands = [datetime(base.year, base.month, base.day, hour, minute)]
        if 1 <= hour < 12:
            cands.append(cands[0] + timedelta(hours=12))
        if day is None:
            cands += [c - timedelta(days=1) for c in cands]
        past = [c for c in cands if c <= now]
        dt = max(past) if past else cands[0]
    return TimeResult(dt, "minute" if minute_given else "hour", method)


def find_datetime(text: str, now: datetime | None = None) -> datetime | None:
    return parse_time(text, now).value

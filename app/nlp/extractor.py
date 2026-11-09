"""Narrative (first free-form turn) extraction. Rules by default; Evon can only add *spans*,
which are then parsed by numbers.py. A model never produces a digit."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from app.gnani import evon
from app.gnani.stt import SttResult
from app.nlp import lexicon_ta as L
from app.nlp import numbers as N
from app.nlp import timeparse as T
from app.nlp import validators as V

Source = Literal["voice_itn", "voice_literal", "both", "evon", "sms", "numpad", "voice"]
FRAUD_TYPES = ["OTP_BANK_CALL", "UPI_COLLECT", "DIGITAL_ARREST", "INVESTMENT", "JOB_TASK", "LOAN_APP",
               "FAKE_CUSTOMER_CARE", "OTHER"]


@dataclass
class Candidate:
    value: str | int
    confidence: Literal["high", "low"]
    source: Source
    span_text: str
    method: str = ""


def _contains(text_norm: str, phrase: str) -> bool:
    p = N.normalise_text(phrase)
    if p.isascii() and len(p) <= 4:
        return f" {p} " in f" {text_norm} "
    return p in text_norm


def find_bank(text: str) -> tuple[str, str] | None:
    t = N.normalise_text(text)
    best: tuple[int, str, str] | None = None
    for canon, aliases in L.BANK_ALIASES.items():
        for a in aliases:
            if _contains(t, a):
                pos = t.find(N.normalise_text(a))
                if best is None or pos < best[0]:
                    best = (pos, canon, a)
    return (best[1], best[2]) if best else None


def find_fraud_type(text: str) -> str | None:
    t = N.normalise_text(text)
    scores: dict[str, int] = {}
    for ftype, cues in L.FRAUD_CUES.items():
        for c in cues:
            if _contains(t, c):
                scores[ftype] = scores.get(ftype, 0) + 1
    if not scores:
        return None
    return max(scores.items(), key=lambda kv: kv[1])[0]


def _cue_positions(ws: list[str], cues: list[str]) -> list[int]:
    pos = []
    norm_cues = [N.normalise_text(c).split() for c in cues]
    for i in range(len(ws)):
        for cw in norm_cues:
            if cw and ws[i:i + len(cw)] == cw:
                pos.append(i)
    return pos


def _near(span: N.Span, cue_pos: list[int], window: int) -> bool:
    return any(span.start - window <= p <= span.end + window for p in cue_pos)


def _amounts_from(text: str) -> list[tuple[int, str, str]]:
    """Every loss amount in a narrative, in order. A figure next to "total" is the sum, not a debit."""
    ws = N.words(text)
    cues = _cue_positions(ws, L.AMOUNT_CUES)
    totals = _cue_positions(ws, L.TOTAL_CUES)
    out: list[tuple[int, str, str]] = []
    for sp in N.find_number_spans(text):
        if sp.amount is None or _near(sp, totals, 2):
            continue
        if (sp.has_currency or sp.has_mult or _near(sp, cues, 6)) and V.validate_amount(sp.amount).ok:
            out.append((sp.amount, sp.text, sp.method))
    return out


def expected_txn_count(text: str) -> int | None:
    """2/3/4 when the caller says how many debits; 2 for a bare "again / innoru"; None if nothing is said."""
    t = N.normalise_text(text)
    best: int | None = None
    for cue, n in L.MULTI_TXN_CUES.items():
        if _contains(t, cue):
            best = max(best or 0, n or 2)
    return best


def _drop_negated_payment_words(text_norm: str) -> str:
    words = re.sub(r"[,.;:!?]", " ", text_norm).split()
    kept = []
    for i, w in enumerate(words):
        after = words[i + 1] if i + 1 < len(words) else ""
        before = words[i - 1] if i else ""
        before2 = words[i - 2] if i > 1 else ""
        ruled_out = (after in L.PAYMENT_NEGATED_AFTER or before in L.PAYMENT_NEGATED_BEFORE
                     or (before in L.PAYMENT_NEGATION_LINKS and before2 in L.PAYMENT_NEGATED_BEFORE))
        if not ruled_out:
            kept.append(w)
    return " ".join(kept)


def find_payment_mode(text: str) -> str | None:
    t = _drop_negated_payment_words(N.normalise_text(text))
    for mode, cues in L.PAYMENT_MODES.items():
        if any(_contains(t, c) for c in cues):
            return mode
    return None


def _phones_from(text: str) -> tuple[tuple[str, str, str] | None, tuple[str, str, str] | None]:
    """(suspect, victim) phone candidates: (digits, span_text, method)."""
    ws = N.words(text)
    sus_cues = _cue_positions(ws, L.SUSPECT_PHONE_CUES)
    vic_cues = _cue_positions(ws, L.VICTIM_PHONE_CUES)
    suspect = victim = None
    for sp in N.find_number_spans(text):
        v = V.validate_phone(sp.digits)
        if not v.ok:
            continue
        before = ws[max(0, sp.start - 3):sp.start]
        is_victim = any(p in range(sp.start - 3, sp.start) for p in vic_cues) or any(
            w in ("en", "என்", "ennoda", "என்னோட", "my") for w in before)
        if is_victim and victim is None:
            victim = (str(v.value), sp.text, sp.method)
        elif suspect is None and (_near(sp, sus_cues, 8) or not is_victim):
            suspect = (str(v.value), sp.text, sp.method)
    return suspect, victim


def _utr_from(text: str) -> tuple[str, str, str] | None:
    for sp in N.find_number_spans(text):
        if len(sp.digits) == 12:
            return sp.digits, sp.text, sp.method
    return None


def _merge(itn: tuple[Any, ...] | None, lit: tuple[Any, ...] | None) -> Candidate | None:
    """Dual-channel: ITN transcript vs pre-ITN literal, parsed independently."""
    if itn and lit:
        if itn[0] == lit[0]:
            return Candidate(itn[0], "high", "both", lit[1], itn[2] if len(itn) > 2 else "")
        return Candidate(lit[0], "low", "voice_literal", lit[1], lit[2] if len(lit) > 2 else "")
    if itn:
        return Candidate(itn[0], "low", "voice_itn", itn[1], itn[2] if len(itn) > 2 else "")
    if lit:
        return Candidate(lit[0], "low", "voice_literal", lit[1], lit[2] if len(lit) > 2 else "")
    return None


def _channels(stt: SttResult) -> tuple[str, str | None, bool]:
    """(itn_text, literal_text, identical). Identical channels (nothing to normalise) count as agreeing."""
    if stt.literal is None:
        return stt.text, None, False
    if stt.literal.strip() == stt.text.strip():
        return stt.text, None, True
    return stt.text, stt.literal, False


def extract_rules(stt: SttResult) -> dict[str, Candidate]:
    text, literal, identical = _channels(stt)
    out: dict[str, Candidate] = {}
    combined = f"{text} {literal or ''}"

    def lit(fn: Callable[[str], Any], src: str | None) -> Any:
        if identical:
            return fn(text)
        return fn(src) if src else None

    bank = find_bank(combined)
    if bank:
        out["bank"] = Candidate(bank[0], "high", "voice", bank[1])
    ft = find_fraud_type(combined)
    if ft:
        out["fraud_type"] = Candidate(ft, "high", "voice", "")

    # every loss amount -> one pre-seeded transaction each ("amount", "amount.1", "amount.2", ...)
    itn_amts = _amounts_from(text)
    lit_amts = lit(_amounts_from, literal) or []
    for i in range(max(len(itn_amts), len(lit_amts))):
        a = _merge(itn_amts[i] if i < len(itn_amts) else None, lit_amts[i] if i < len(lit_amts) else None)
        if a:
            out["amount" if i == 0 else f"amount.{i}"] = a
    n = expected_txn_count(combined)
    if n:
        out["expected_txn_count"] = Candidate(n, "low", "voice", "")
    pm = find_payment_mode(combined)
    if pm:
        out["payment_mode"] = Candidate(pm, "low", "voice", "")
    tr = T.parse_time(text)
    if tr.value is None and literal:
        tr = T.parse_time(literal)
    if tr.value is not None:
        out["datetime"] = Candidate(tr.value.strftime(T.FMT), "low", "voice", "", tr.precision or "")

    s_itn, v_itn = _phones_from(text)
    s_lit, v_lit = lit(_phones_from, literal) or (None, None)
    s = _merge(s_itn, s_lit)
    if s:
        out["suspect_phone"] = s
    v = _merge(v_itn, v_lit)
    if v:
        out["victim_mobile"] = v

    u = _merge(_utr_from(text), lit(_utr_from, literal))
    if u:
        out["utr"] = u
    return out


async def extract_narrative(stt: SttResult) -> dict[str, Candidate]:
    out = extract_rules(stt)
    data = await evon.extract(stt.text, stt.literal)
    if not data:
        return out
    source_text = f"{stt.text}\n{stt.literal or ''}"
    if "bank" not in out and isinstance(data.get("bank"), str):
        hit = find_bank(data["bank"])
        if hit:
            out["bank"] = Candidate(hit[0], "low", "evon", data["bank"])
    if "fraud_type" not in out and data.get("fraud_type") in FRAUD_TYPES:
        out["fraud_type"] = Candidate(data["fraud_type"], "low", "evon", "")
    slots = data.get("slots") or {}
    for key, field in [("amount_span", "amount"), ("suspect_phone_span", "suspect_phone"),
                       ("victim_phone_span", "victim_mobile"), ("utr_span", "utr")]:
        span = slots.get(key)
        if field in out or not isinstance(span, str) or not span.strip():
            continue
        if span not in source_text:  # spans must be verbatim substrings
            continue
        if field == "amount":
            r = N.parse_amount(span)
            if isinstance(r.value, int) and V.validate_amount(r.value).ok:
                out[field] = Candidate(r.value, "low", "evon", span, r.method)
        else:
            want = 12 if field == "utr" else 10
            r = N.parse_digit_string(span, want)
            ok = V.validate_utr(str(r.value)).ok if field == "utr" else V.validate_phone(str(r.value)).ok
            if r.value and ok:
                out[field] = Candidate(str(r.value), "low", "evon", span, r.method)
    return out


def find_district(text: str) -> str | None:
    t = N.normalise_text(text)
    for canon, aliases in L.DISTRICTS.items():
        for a in aliases:
            if N.normalise_text(a) in t:
                return canon
    return None


def find_datetime(text: str, now: datetime | None = None) -> datetime | None:
    return T.find_datetime(text, now)


def find_upi(text: str) -> str | None:
    """Spoken VPA: 'ramesh dot k at ybl' -> 'ramesh.k@ybl'."""
    t = N.normalise_text(text)
    t = re.sub(r"\s+(?:at the rate of|at the rate|அட் தி ரேட்|அட் த ரேட்|at|அட்)\s+", "@", t)
    t = re.sub(r"\s+(?:dot|டாட்)\s+", ".", t)
    m = re.search(r"([\w.\-]{2,})\s*@\s*([a-z]{2,64})", t)
    return f"{m.group(1)}@{m.group(2)}" if m else None

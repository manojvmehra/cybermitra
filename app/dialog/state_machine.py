"""Per-call dialogue FSM. next_state() is pure: no network, no clock except session timestamps.

CONSENT → OPENING (one question for the whole story) → NARRATIVE
  → STORY_CHECK (one yes/no for what the story gave: amount, time, payment mode, bank; "no" reads each back)
  → TXN loop: GAP_FILL(amount → datetime) → READBACK(each) → ASK_MORE_TXN ↺
  → CASE fields: GAP_FILL(victim_bank … victim_name) → READBACK
  → typed numbers last: utr (each txn) → suspect_phone → victim_mobile
  → QUEUED (spoken summary, "we will send an SMS", the call ends)
Any state → HANDOFF_HUMAN | HANDOFF_NONFIN | HANDOFF_WELLBEING
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime

from app.config import get_settings
from app.dialog import prompts, readback
from app.dialog.models import (
    CASE_FIELDS,
    DIGIT_FIELDS,
    MAX_REPAIRS,
    NO_READBACK,
    OPTIONAL_FIELDS,
    TXN_FIELDS,
    Action,
    Event,
    FieldState,
    HandoffReason,
    ReadbackCursor,
    Session,
    Txn,
)
from app.gnani.stt import SttResult
from app.nlp import extractor as X
from app.nlp import numbers as N
from app.nlp import safety, yesno
from app.nlp import timeparse as T
from app.nlp import validators as V
from app.nlp.sms_parser import parse_sms_multi, sms_datetime

TERMINAL = {"HANDOFF_HUMAN", "HANDOFF_NONFIN", "HANDOFF_WELLBEING", "END", "QUEUED"}
TEXT_FIELDS = {"victim_bank", "suspect_bank", "payment_mode", "datetime", "victim_name", "district", "suspect_upi",
               "called_bank"}
YESNO_BUTTONS = {"more_txn", "review", "dup_utr", "called_bank", "story"}
# What the opening asks the caller to tell in one go, checked with a single yes/no
STORY_FIELDS = (("amount", True), ("datetime", True), ("payment_mode", False), ("victim_bank", False))
# Typed on the keypad, so asked last, after everything the caller can just say
TYPED_LAST = ("suspect_phone", "victim_mobile")
# Number questions: star then the number then hash types it; 2 means "don't know"
KEYPAD_FIELDS = {*DIGIT_FIELDS, "amount"}
UNKNOWN_HANDOFF = 3
GAVE_UP_HANDOFF = 2
MAX_BACK_STEPS = 30
UNDOABLE = {"AUDIO_TURN", "SMS_PASTED", "BUTTON", "NUMPAD", "SKIP"}
# Back undoes the caller's answers, never the call's limits or record: these survive a step back.
KEPT_ON_BACK = {"history", "transcripts", "turns", "api_turns", "silence_count", "unknown_streak", "created_at",
                "last_active", "last_prompt_text"}


# ---------------------------------------------------------------- action helpers
def _speak(s: Session, acts: list[Action], pid: str | None = None, text: str | None = None,
           speed: str = "prompt", **kw: object) -> None:
    t = text if text is not None else prompts.text(pid or "", s.lang, s.channel, **kw)
    acts.append(Action(type="SpeakPrompt", prompt_id=pid if text is None and not kw else None, text=t,
                       speed=speed))  # type: ignore[arg-type]
    s.last_prompt_text = t


def _update(s: Session, acts: list[Action]) -> None:
    acts.append(Action(type="UpdateFields"))


def _end(s: Session) -> None:
    s.readback = None
    s.current_field = None
    s.current_txn = None
    s.show_numpad = False
    s.ended_at = time.time()


def _handoff(s: Session, acts: list[Action], kind: str, reason: HandoffReason) -> None:
    s.state = kind  # type: ignore[assignment]
    s.handoff = kind
    s.handoff_reason = reason
    _end(s)
    _speak(s, acts, kind)
    acts.append(Action(type="Handoff", data={"kind": kind, "reason": reason}))
    acts.append(Action(type="PushPacket", data={"status": "needs_human", "reason": reason}))


def _queue(s: Session, acts: list[Action]) -> None:
    """One spoken summary and goodbye; the next steps go in the SMS (the summary on screen in the demo)."""
    s.state = "QUEUED"
    _end(s)
    facts = _facts(s, [(n, t, f) for n, txn, t, f in story_items(s, settled_only=True)])
    _speak(s, acts, "QUEUED", facts=facts or prompts.text("NO_FACTS", s.lang, s.channel))
    acts.append(Action(type="PushPacket", data={"status": "ready_for_review"}))
    acts.append(Action(type="ShowSummary"))


def _key(field: str, txn: int | None) -> str:
    return f"{field}#{txn}" if field in TXN_FIELDS else field


def _set(f: FieldState, value: str | int | None, *, status: str, source: str | None,
         confidence: str | None = None, span: str = "", precision: str | None = None) -> None:
    f.value = value
    f.status = status  # type: ignore[assignment]
    f.source = source
    f.confidence = confidence  # type: ignore[assignment]
    f.span_text = span
    f.precision = precision


def _repair(s: Session, field: str, txn: int | None) -> bool:
    """Count a repair attempt. Returns False when the field has used up its repairs."""
    k = _key(field, txn)
    n = s.repair_attempts.get(k, 0)
    if n >= MAX_REPAIRS:
        return False
    s.repair_attempts[k] = n + 1
    return True


def _give_up(s: Session, acts: list[Action], field: str, txn: int | None) -> None:
    f = s.field(field, txn)
    if f.value is None and field in OPTIONAL_FIELDS:
        f.status = "skipped"
    else:
        f.status = "unconfirmed"
        s.gave_up += 1
    s.readback = None
    if s.gave_up >= GAVE_UP_HANDOFF:
        # two fields the AI could not get right: a person will do better than a third attempt
        _handoff(s, acts, "HANDOFF_HUMAN", "repairs_exhausted")
        return
    _speak(s, acts, "UNCONFIRMED")
    _advance(s, acts)


def _not_understood(s: Session, acts: list[Action]) -> bool:
    """Count an unclear answer to a yes/no question. True if the call was handed off."""
    s.unknown_streak += 1
    if s.unknown_streak >= UNKNOWN_HANDOFF:
        _handoff(s, acts, "HANDOFF_HUMAN", "not_understood")
        return True
    return False


# ---------------------------------------------------------------- flow
def _prefix(s: Session, field: str, txn: int | None) -> str:
    if field in TXN_FIELDS and txn is not None and (len(s.txns) > 1 or (s.expected_txn_count or 1) > 1):
        return prompts.text("TXN_PREFIX", s.lang, s.channel, n=txn + 1)
    return ""


def _ask(s: Session, acts: list[Action], field: str, txn: int | None) -> None:
    s.state = "GAP_FILL"
    s.current_field = field
    s.current_txn = txn if field in TXN_FIELDS else None
    s.readback = None
    # UTR and mobile numbers are typed. Typing starts only when the caller presses star, as the question says,
    # so until then 2 means "don't know" and 3 repeats.
    s.show_numpad = False
    pre = _prefix(s, field, txn)
    if pre:
        _speak(s, acts, text=pre + prompts.text(f"ASK_{field}", s.lang, s.channel))
    else:
        _speak(s, acts, f"ASK_{field}")


def _ask_again(s: Session, acts: list[Action]) -> None:
    assert s.current_field is not None
    pre = _prefix(s, s.current_field, s.current_txn)
    if pre:
        _speak(s, acts, text=pre + prompts.text(f"ASK_{s.current_field}", s.lang, s.channel))
    else:
        _speak(s, acts, f"ASK_{s.current_field}")


def _start_readback(s: Session, acts: list[Action], field: str, txn: int | None) -> None:
    f = s.field(field, txn)
    assert f.value is not None
    s.state = "READBACK"
    s.current_field = field
    s.current_txn = txn if field in TXN_FIELDS else None
    chunks = readback.chunk(field, f.value)
    if field == "datetime":
        chunks = [readback.with_precision(str(f.value), f.precision)]
    s.readback = ReadbackCursor(field=field, txn_index=s.current_txn, chunks=chunks)
    s.show_numpad = f.confidence == "low" and field in DIGIT_FIELDS
    _say_chunk(s, acts)


def _say_chunk(s: Session, acts: list[Action]) -> None:
    rb = s.readback
    assert rb is not None
    st = readback.step(rb.field, rb.chunks, rb.index, s.lang, rb.txn_index, len(s.txns))
    acts.append(Action(type="ShowReadback", data={
        "field": st.field, "txn_index": rb.txn_index, "chunk_index": st.chunk_index,
        "chunk_display": st.chunk_digits, "total_chunks": st.total_chunks, "numpad": s.show_numpad}))
    _speak(s, acts, text=st.text, speed="readback")


def _next_open(s: Session, f: FieldState, field: str, txn: int | None, acts: list[Action]) -> bool:
    if f.settled:
        return False
    if f.value is not None and field not in NO_READBACK:
        _start_readback(s, acts, field, txn)
    elif f.value is not None:
        f.status = "confirmed"
        return False
    else:
        _ask(s, acts, field, txn)
    return True


def _upi_not_relevant(s: Session, name: str) -> bool:
    """Ask for a UPI ID only on a UPI payment. A value already captured is still checked, so it reaches the packet."""
    return name == "suspect_upi" and s.fields[name].value is None and s.fields["payment_mode"].value != "UPI"


def _advance(s: Session, acts: list[Action]) -> None:
    _update(s, acts)
    if s.phase == "TXN":
        if not s.txns:
            s.txns.append(Txn())
        for i, t in enumerate(s.txns):
            if t.done:
                continue
            s.txn_cursor = i
            for name in TXN_FIELDS:
                if name != "utr" and _next_open(s, t.fields[name], name, i, acts):
                    return
        if len(s.txns) >= get_settings().MAX_TXNS:
            if (s.expected_txn_count or 0) > len(s.txns):  # the caller mentioned more than we take on this call
                _speak(s, acts, "MAX_TXNS")
            s.phase = "CASE"
        else:
            s.state = "ASK_MORE_TXN"
            s.current_field = None
            s.current_txn = None
            s.readback = None
            if s.expected_txn_count and len(s.txns) < s.expected_txn_count:
                _speak(s, acts, "MORE_TXN_EXPECTED", n=s.expected_txn_count)
            _speak(s, acts, "ASK_MORE_TXN")
            return
    for name in CASE_FIELDS:
        if name in TYPED_LAST or _upi_not_relevant(s, name):
            continue
        if _next_open(s, s.fields[name], name, None, acts):
            return
    for i, t in enumerate(s.txns):
        if _next_open(s, t.fields["utr"], "utr", i, acts):
            return
    for name in TYPED_LAST:
        if _next_open(s, s.fields[name], name, None, acts):
            return
    _review(s, acts)


def _review(s: Session, acts: list[Action]) -> None:
    """Every field has been checked one by one, so the call ends with a summary rather than another question."""
    _queue(s, acts)


# ---------------------------------------------------------------- the story, checked in one go
def story_items(s: Session, settled_only: bool = False) -> list[tuple[str, int | None, str, FieldState]]:
    """(field, txn, words for it, state) for the story fields that have a value: pending ones for the check,
    confirmed ones for the closing summary."""
    out: list[tuple[str, int | None, str, FieldState]] = []
    for name, in_txn in STORY_FIELDS:
        targets: list[tuple[int | None, FieldState]] = (
            [(i, t.fields[name]) for i, t in enumerate(s.txns)] if in_txn else [(None, s.fields[name])])
        for i, f in targets:
            if f.value is None or (f.status != "confirmed" if settled_only else f.status != "pending"):
                continue
            if name == "datetime":
                words = readback.render_datetime(readback.with_precision(str(f.value), f.precision), s.lang)
            elif name == "amount":
                words = readback.chunk_words("amount", str(f.value), s.lang)
            else:
                words = prompts.text(f"FACT_{name}", s.lang, s.channel, v=f.value)
            out.append((name, i, words, f))
    return out


def _facts(s: Session, items: list[tuple[str, str, FieldState]]) -> str:
    return ", ".join(words for _, words, _ in items)


def _story_check(s: Session, acts: list[Action]) -> None:
    items = story_items(s)
    if not items:
        _advance(s, acts)
        return
    s.state = "STORY_CHECK"
    s.current_field = None
    s.current_txn = None
    s.readback = None
    _update(s, acts)
    _speak(s, acts, "STORY_CHECK", facts=_facts(s, [(n, w, f) for n, _, w, f in items]))


def _story_answer(s: Session, acts: list[Action], yes: bool) -> None:
    s.unknown_streak = 0
    if not yes:
        _speak(s, acts, "STORY_ONE_BY_ONE")
        _advance(s, acts)  # each pending value is read back on its own, so the caller can fix the wrong one
        return
    for name, _, _, f in story_items(s):
        f.status = "confirmed"
        if name == "amount" and isinstance(f.value, int) and V.validate_amount(f.value).extra_confirm:
            _speak(s, acts, "HIGH_AMOUNT")
        if name == "datetime" and isinstance(f.value, str):
            dt = sms_datetime(f.value)
            if dt and V.validate_datetime(dt).warn:
                f.warn = "older_than_7_days"
                _speak(s, acts, "OLD_DATE")
    _advance(s, acts)


def _new_txn(s: Session, acts: list[Action]) -> None:
    s.txns.append(Txn())
    s.txn_cursor = len(s.txns) - 1
    _advance(s, acts)


def _field_confirmed(s: Session, acts: list[Action], field: str, txn: int | None) -> None:
    f = s.field(field, txn)
    f.status = "confirmed"
    s.readback = None
    if field == "amount" and isinstance(f.value, int) and V.validate_amount(f.value).extra_confirm:
        _speak(s, acts, "HIGH_AMOUNT")
    if field == "datetime" and isinstance(f.value, str):
        dt = sms_datetime(f.value)
        if dt and V.validate_datetime(dt).warn:
            f.warn = "older_than_7_days"
            _speak(s, acts, "OLD_DATE")
    _advance(s, acts)


# ---------------------------------------------------------------- parsing answers
@dataclass
class Parsed:
    value: str | int | None
    confidence: str = ""
    source: str = ""
    reason: str = ""
    precision: str | None = None


def _parse_field(field: str, text: str, literal: str | None, now: datetime | None = None) -> Parsed:
    lit = literal if literal and literal.strip() != text.strip() else None
    if field == "amount":
        a = N.parse_amount(text).value
        b = N.parse_amount(lit).value if lit else None
        if a is not None and (lit is None and literal is not None or a == b):
            return Parsed(a, "high", "both")
        if b is not None:
            return Parsed(b, "low", "voice_literal")
        if a is not None:
            return Parsed(a, "low", "voice_itn")
        return Parsed(None, reason="unparsed")
    if field in DIGIT_FIELDS:
        n = DIGIT_FIELDS[field]
        validate = V.validate_utr if field == "utr" else V.validate_phone
        ra = N.parse_digit_string(text, n).value
        rb = N.parse_digit_string(lit, n).value if lit else None
        va = validate(str(ra)) if ra else None
        vb = validate(str(rb)) if rb else None
        if va and va.ok and (lit is None and literal is not None or (vb and vb.ok and vb.value == va.value)):
            return Parsed(str(va.value), "high", "both")
        if vb and vb.ok:
            return Parsed(str(vb.value), "low", "voice_literal")
        if va and va.ok:
            return Parsed(str(va.value), "low", "voice_itn")
        heard = (va or vb)
        return Parsed(None, reason=heard.reason if heard else "unparsed")
    joined = f"{text} {literal or ''}"
    if field in ("victim_bank", "suspect_bank"):
        bank = X.find_bank(joined)
        return Parsed(bank[0], "high", "voice") if bank else Parsed(None, reason="unparsed")
    if field == "payment_mode":
        pm = X.find_payment_mode(joined)
        return Parsed(pm, "high", "voice") if pm else Parsed(None, reason="unparsed")
    if field == "datetime":
        tr = T.parse_time(text, now)
        if tr.value is None and lit:
            tr = T.parse_time(lit, now)
        if tr.value is None:
            return Parsed(None, reason="future" if "future" in tr.warnings else "unparsed")
        v = V.validate_datetime(tr.value, now)
        if not v.ok:
            return Parsed(None, reason=v.reason)
        return Parsed(tr.value.strftime(T.FMT), "high", "voice", precision=tr.precision)
    if field == "district":
        d = X.find_district(joined)
        return Parsed(d, "high", "voice") if d else Parsed(None, reason="unparsed")
    if field == "suspect_upi":
        u = X.find_upi(text) or (X.find_upi(lit) if lit else None)
        if u and V.validate_upi(u).ok:
            return Parsed(u, "low", "voice")
        return Parsed(None, reason="unparsed")
    if field == "victim_name":
        name = clean_name(text)
        return Parsed(name, "low", "voice") if name else Parsed(None, reason="unparsed")
    return Parsed(None, reason="unknown_field")


_NAME_FILLER = re.compile(
    r"(?i)\b(my name is|my name|name is|i am|this is|en peru|en per|ennoda peru|ennoda per|naan|nu peru|nu per|"
    r"peru|sir|madam|mam)\b|என் பெயர்|என் பேர்|என்னோட பேரு|என்னோட பெயர்|என் பேரு|னு பேரு|னு பெயர்|பேரு|பெயர்|"
    r"நான்|சார்|மேடம்")


def clean_name(text: str) -> str:
    """'என் பெயர் ரமேஷ்ங்க' -> 'ரமேஷ்'; 'my name is Test Kumar sir' -> 'Test Kumar'."""
    name = _NAME_FILLER.sub(" ", text or "")
    name = re.sub(r"[^\w\s.஀-௿]", " ", name)
    parts = name.split()
    if parts and parts[-1].endswith("ங்க") and len(parts[-1]) > 4:  # polite suffix
        parts[-1] = parts[-1][: -len("ங்க")]
    return " ".join(parts).strip()[:60]


def _typed_text(field: str, raw: str) -> tuple[bool, str | None, str | None]:
    """Typed input for a text field -> (ok, value, precision). Authoritative, but normalised like speech."""
    t = re.sub(r"\s+", " ", raw).strip()[:80]
    if not t:
        return False, None, None
    if field in ("victim_bank", "suspect_bank"):
        b = X.find_bank(t)
        return True, b[0] if b else t, None
    if field == "payment_mode":
        return True, X.find_payment_mode(t) or t, None
    if field == "district":
        return True, X.find_district(t) or t, None
    if field == "called_bank":
        yn = yesno.classify(t).intent
        return (yn in ("YES", "NO")), {"YES": "yes", "NO": "no"}.get(yn), None
    if field == "datetime":
        tr = T.parse_time(t)
        if tr.value is None:
            return ("future" not in tr.warnings), (t if "future" not in tr.warnings else None), None
        v = V.validate_datetime(tr.value)
        return v.ok, tr.value.strftime(T.FMT) if v.ok else None, tr.precision
    if field == "suspect_upi":
        v = V.validate_upi(t)
        return v.ok, str(v.value) if v.ok else None, None
    if field == "victim_name":
        name = clean_name(t)
        return bool(name), name or None, None
    return True, t, None


def _wrong_len_prompt(s: Session, acts: list[Action], field: str, reason: str) -> bool:
    if reason == "phone_prefix":  # ten digits, but no Indian mobile starts with 0-5
        _speak(s, acts, "BAD_PHONE")
        return True
    m = re.match(r"(utr|phone)_len_(\d+)", reason)
    if not m or m.group(2) == "0":
        return False
    pid = "WRONG_LEN_utr" if field == "utr" else "WRONG_LEN_phone"
    _speak(s, acts, pid, n=int(m.group(2)))
    return True


def is_asked(s: Session, field: str, txn: int | None) -> bool:
    return s.current_field == field and (field not in TXN_FIELDS or txn == s.current_txn)


def _dup_utr_of(s: Session, utr: str, txn: int | None) -> bool:
    return any(i != txn and t.fields["utr"].value == utr for i, t in enumerate(s.txns))


def _gap_answer(s: Session, acts: list[Action], text: str, literal: str | None) -> None:
    field, txn = s.current_field, s.current_txn
    assert field is not None
    f = s.field(field, txn)
    yn = yesno.classify(text)
    if field == "called_bank":
        if yn.intent in ("YES", "NO"):
            _set(f, "yes" if yn.intent == "YES" else "no", status="confirmed", source="voice", confidence="high")
            _advance(s, acts)
            return
        if yn.intent != "DONT_KNOW":
            if not _not_understood(s, acts):
                _speak(s, acts, "CONFIRM_HINT")
                _ask_again(s, acts)
            return
    if yn.intent == "DONT_KNOW" or (yn.intent == "NO" and field in OPTIONAL_FIELDS):
        f.status = "skipped"
        _speak(s, acts, "SKIPPED")
        _advance(s, acts)
        return
    if yn.intent == "REPEAT":
        _ask_again(s, acts)
        return
    p = _parse_field(field, text, literal)
    if p.value is None and field in DIGIT_FIELDS and p.reason in ("unparsed", "utr_len_0", "phone_len_0"):
        # No number in what was heard (noise, "hmm"): this question is answered on the keypad, so explain how
        # rather than count a failed answer.
        _speak(s, acts, "USE_NUMPAD")
        return
    if p.value is not None:
        if field == "utr" and _dup_utr_of(s, str(p.value), txn):
            s.state = "DUP_CHECK"
            s.dup_utr = str(p.value)
            _speak(s, acts, "DUP_UTR")
            return
        _set(f, p.value, status="pending", source=p.source, confidence=p.confidence, span=text[:80],
             precision=p.precision)
        _start_readback(s, acts, field, txn)
        return
    if not _repair(s, field, txn):
        _give_up(s, acts, field, txn)
        return
    if field == "amount":
        _speak(s, acts, "TYPE_amount")  # an amount the AI cannot understand is typed instead
        return
    if field in DIGIT_FIELDS and _wrong_len_prompt(s, acts, field, p.reason):
        return  # that prompt already says how to type it again
    _speak(s, acts, "DIDNT_CATCH")
    _ask_again(s, acts)


def _dup_answer(s: Session, acts: list[Action], same: bool) -> None:
    txn = s.current_txn
    s.dup_utr = None
    if same and txn is not None and len(s.txns) > 1:
        # the caller described the same debit twice: keep the first one only
        s.txns.pop(txn)
        s.txn_cursor = max(0, min(s.txn_cursor, len(s.txns) - 1))
        _speak(s, acts, "DUP_DROPPED")
        _advance(s, acts)
        return
    if not _repair(s, "utr", txn):
        _give_up(s, acts, "utr", txn)
        return
    s.state = "GAP_FILL"
    s.show_numpad = True
    acts.append(Action(type="ShowNumpad", data={"field": "utr", "txn_index": txn}))
    _ask_again(s, acts)


def _readback_no(s: Session, acts: list[Action]) -> None:
    rb = s.readback
    assert rb is not None
    field, txn = rb.field, rb.txn_index
    if not _repair(s, field, txn):
        _give_up(s, acts, field, txn)
        return
    if field in TEXT_FIELDS:
        f = s.field(field, txn)
        f.value = None
        f.status = "empty"
        _ask(s, acts, field, txn)
        return
    rb.awaiting = "correct"
    s.show_numpad = True
    acts.append(Action(type="ShowNumpad", data={"field": field, "txn_index": txn, "chunk_index": rb.index}))
    _speak(s, acts, "CORRECT_CHUNK")


def _replace_chunk(s: Session, acts: list[Action], new_chunk: str) -> None:
    rb = s.readback
    assert rb is not None
    f = s.field(rb.field, rb.txn_index)
    if new_chunk != rb.chunks[rb.index]:
        f.corrections += 1
    rb.chunks[rb.index] = new_chunk
    rb.unclear = 0
    joined = "".join(rb.chunks)
    f.value = int(joined) if rb.field == "amount" else joined
    f.source = "voice" if f.source in ("both", "voice_itn", "voice_literal") else f.source
    rb.awaiting = "confirm"
    _say_chunk(s, acts)


def _full_value_said(field: str, text: str) -> str | None:
    """If the user re-said the whole number (not just the chunk), return it."""
    if field in DIGIT_FIELDS:
        n = DIGIT_FIELDS[field]
        d = N.parse_digit_string(text, n).value
        validate = V.validate_utr if field == "utr" else V.validate_phone
        if d and len(str(d)) == n and validate(str(d)).ok:
            return str(d)
    return None


def _replace_whole(s: Session, acts: list[Action], new_value: str) -> None:
    """Swap in a fully re-said number and resume at the first chunk that changed
    (chunks before it were already confirmed and are identical)."""
    rb = s.readback
    assert rb is not None
    f = s.field(rb.field, rb.txn_index)
    new_chunks = readback.chunk(rb.field, new_value)
    first_diff = next((i for i, (a, b) in enumerate(zip(rb.chunks, new_chunks, strict=False)) if a != b),
                      len(new_chunks) - 1)
    f.value = new_value
    f.corrections += 1
    f.source = "voice"
    rb.chunks = new_chunks
    rb.index = min(first_diff, rb.index)
    rb.awaiting = "confirm"
    rb.unclear = 0
    _say_chunk(s, acts)


def _readback_answer(s: Session, acts: list[Action], text: str, literal: str | None) -> None:
    rb = s.readback
    assert rb is not None
    field, txn = rb.field, rb.txn_index
    chunk_now = rb.chunks[rb.index]
    yn = yesno.classify(text)
    if yn.intent != "UNKNOWN":
        s.unknown_streak = 0

    if yn.intent == "REPEAT":
        _say_chunk(s, acts)
        return
    if yn.intent == "DONT_KNOW":
        _give_up(s, acts, field, txn)
        return

    # The user re-said the whole number: same as what we have → confirm it, different → correct it.
    full = _full_value_said(field, text) if yn.intent in ("CORRECTION", "NO") else None
    if full is not None:
        current = s.field(field, txn).value
        if full == current and yn.intent != "NO":
            rb.index = len(rb.chunks) - 1
            _chunk_yes(s, acts)
        elif full != current:
            if not _repair(s, field, txn):
                _give_up(s, acts, field, txn)
                return
            _replace_whole(s, acts, full)
        else:
            _readback_no(s, acts)
        return

    if rb.awaiting == "confirm":
        if yn.intent == "YES":
            _chunk_yes(s, acts)
            return
        if yn.intent == "CORRECTION":
            new = _correction_value(field, chunk_now, text, yn)
            if new == chunk_now and yn.position is None:
                _chunk_yes(s, acts)  # they repeated the chunk back: that is a confirmation
                return
            if not _repair(s, field, txn):
                _give_up(s, acts, field, txn)
                return
            if new is not None:
                _replace_chunk(s, acts, new)
            else:
                rb.awaiting = "correct"
                s.show_numpad = True
                acts.append(Action(type="ShowNumpad", data={"field": field, "txn_index": txn,
                                                            "chunk_index": rb.index}))
                _speak(s, acts, "USE_NUMPAD")
            return
        if yn.intent == "UNKNOWN":
            if _not_understood(s, acts):
                return
            if rb.unclear < 1:
                # Unclear ("ம்", noise): never confirm, re-ask once with a hint without spending a repair.
                # A second unclear answer is treated as "no" (any doubt counts as no).
                rb.unclear += 1
                _speak(s, acts, "CONFIRM_HINT")
                _say_chunk(s, acts)
                return
        _readback_no(s, acts)
        return

    # awaiting == "correct"
    if yn.intent == "UNKNOWN" and _not_understood(s, acts):
        return
    if yn.intent == "YES" and not yn.digits:
        rb.awaiting = "confirm"
        _chunk_yes(s, acts)
        return
    new = _correction_value(field, chunk_now, text, yn)
    if new is not None:
        _replace_chunk(s, acts, new)
        return
    acts.append(Action(type="ShowNumpad", data={"field": field, "txn_index": txn, "chunk_index": rb.index}))
    _speak(s, acts, "USE_NUMPAD")


def _correction_value(field: str, chunk_now: str, text: str, yn: yesno.YesNo) -> str | None:
    if field == "amount":
        v = N.parse_amount(text).value
        return str(v) if isinstance(v, int) and V.validate_amount(v).ok else None
    if yn.digits:
        return yesno.apply_correction(chunk_now, yn)
    d = N.parse_digit_string(text, len(chunk_now)).value
    return str(d) if d and len(str(d)) == len(chunk_now) else None


def _chunk_yes(s: Session, acts: list[Action]) -> None:
    rb = s.readback
    assert rb is not None
    rb.index += 1
    rb.awaiting = "confirm"
    rb.unclear = 0
    if rb.index >= len(rb.chunks):
        _field_confirmed(s, acts, rb.field, rb.txn_index)
    else:
        _say_chunk(s, acts)


def _more_txn_answer(s: Session, acts: list[Action], text: str) -> None:
    yn = yesno.classify(text)
    t = N.normalise_text(text)
    more = any(c in t for c in ("innoru", "இன்னொரு", "another", "irukku", "இருக்கு"))
    no_more = any(c in t for c in ("mattum thaan", "மட்டும் தான்", "vera illa", "வேற இல்ல", "only one", "that's all"))
    if no_more or (yn.intent in ("NO", "DONT_KNOW") and not more):
        s.unknown_streak = 0
        s.phase = "CASE"
        _advance(s, acts)
    elif more or yn.intent == "YES":
        s.unknown_streak = 0
        _new_txn(s, acts)
    elif not _not_understood(s, acts):
        _speak(s, acts, "CONFIRM_HINT")
        _speak(s, acts, "ASK_MORE_TXN")


# ---------------------------------------------------------------- narrative + sms
def _narrative(s: Session, acts: list[Action], ev: Event) -> None:
    cands = ev.candidates
    if cands is None:
        stt = SttResult(text=ev.text, literal=ev.literal, model="", detected_language=None,
                        truncated=False, latency_ms=0, cached=False)
        cands = {k: c.__dict__ for k, c in X.extract_rules(stt).items()}
    cands = {k: (c if isinstance(c, dict) else c.__dict__) for k, c in cands.items()}

    amounts = [cands[k] for k in sorted((k for k in cands if k == "amount" or k.startswith("amount.")),
                                        key=lambda k: 0 if k == "amount" else int(k.split(".")[1]))]
    known = {t.fields["amount"].value for t in s.txns}  # e.g. already pasted from an SMS
    for c in amounts:
        if c["value"] in known or len(s.txns) >= get_settings().MAX_TXNS:
            continue
        t = Txn()
        _set(t.fields["amount"], c["value"], status="pending", source=c["source"], confidence=c["confidence"],
             span=str(c.get("span_text", ""))[:80])
        s.txns.append(t)
    if not s.txns:
        s.txns.append(Txn())
    if len(s.txns) == 1:  # a single debit: the time and UTR in the story belong to it
        for name in ("datetime", "utr"):
            c = cands.get(name)
            f = s.txns[0].fields[name]
            if name == "datetime" and c and c.get("method") == "day":
                continue  # "nethu" alone: ask for the time rather than read back a made-up noon
            if c and f.status == "empty":
                _set(f, c["value"], status="pending", source=c["source"], confidence=c["confidence"],
                     span=str(c.get("span_text", ""))[:80], precision=c.get("method") or None)
    if "expected_txn_count" in cands:
        s.expected_txn_count = int(cands["expected_txn_count"]["value"])
    heard = len({c["value"] for c in amounts} | {k for k in known if k is not None})
    s.expected_txn_count = max(s.expected_txn_count or 0, heard) or None

    for name, case_name in (("bank", "victim_bank"), ("suspect_phone", "suspect_phone"),
                            ("victim_mobile", "victim_mobile"), ("payment_mode", "payment_mode"),
                            ("fraud_type", "fraud_type")):
        c = cands.get(name)
        f = s.fields[case_name]
        if not c or f.status != "empty":
            continue
        status = "confirmed" if case_name == "fraud_type" else "pending"
        _set(f, c["value"], status=status, source=c["source"], confidence=c["confidence"],
             span=str(c.get("span_text", ""))[:80])
    if s.fields["fraud_type"].value is None:
        _set(s.fields["fraud_type"], "OTHER", status="confirmed", source="rules")
    s.txn_cursor = 0
    _story_check(s, acts)


def _sms_target(s: Session, amount: object) -> int | None:
    """The transaction the first pasted SMS fills: the one being asked about, unless it already has
    a different confirmed amount or a UTR. Otherwise a new transaction is opened."""
    if s.phase != "TXN" or s.state not in ("NARRATIVE", "GAP_FILL", "READBACK") or not s.txns:
        return None
    t = s.txns[s.txn_cursor]
    a, u = t.fields["amount"], t.fields["utr"]
    if u.status == "confirmed" or (a.status == "confirmed" and amount is not None and a.value != amount):
        return None
    return s.txn_cursor


def _apply_sms(s: Session, acts: list[Action], text: str) -> None:
    parsed_all = parse_sms_multi(text)
    added = over_cap = 0
    for n, parsed in enumerate(parsed_all):
        for key, case_key in (("bank", "victim_bank"), ("suspect_upi", "suspect_upi"),
                              ("victim_account_last4", "victim_account_last4")):
            f = parsed.get(key)
            if f is None or s.fields[case_key].status == "confirmed":
                continue
            if key == "suspect_upi" and not V.validate_upi(str(f.value)).ok:
                continue
            _set(s.fields[case_key], f.value, status="confirmed", source="sms", confidence="high",
                 span=f.raw_span[:40])
        pm = s.fields["payment_mode"]
        if pm.status != "confirmed" and ("suspect_upi" in parsed or re.search(r"(?i)\bupi\b", text)):
            _set(pm, "UPI", status="confirmed", source="sms", confidence="high")

        utr = parsed.get("utr")
        if utr is not None and not V.validate_utr(str(utr.value)).ok:
            utr = None
        if utr is not None and _dup_utr_of(s, str(utr.value), None):
            continue  # this SMS is a debit we already have
        txn_parts = {k: parsed[k] for k in ("amount", "datetime") if k in parsed}
        if utr is not None:
            txn_parts["utr"] = utr
        if not txn_parts:
            continue
        amt = txn_parts["amount"].value if "amount" in txn_parts else None
        idx = _sms_target(s, amt) if n == 0 else None
        if idx is None:
            if len(s.txns) >= get_settings().MAX_TXNS:
                over_cap += 1
                continue
            s.txns.append(Txn())
            idx = len(s.txns) - 1
        for key, f in txn_parts.items():
            prec = ("minute" if ":" in str(f.value) else "day") if key == "datetime" else None
            _set(s.txns[idx].fields[key], f.value, status="confirmed", source="sms", confidence="high",
                 span=f.raw_span[:40], precision=prec)
        added += 1
    if over_cap:
        s.expected_txn_count = max(s.expected_txn_count or 0, len(s.txns) + over_cap)
    _update(s, acts)
    if not parsed_all:
        _speak(s, acts, "DIDNT_CATCH")
        return
    _speak(s, acts, "SMS_THANKS")
    if s.state == "NARRATIVE":
        return  # still waiting for the story
    if s.state == "STORY_CHECK":
        _story_check(s, acts)
        return
    cur = s.current_field
    cur_settled = cur is not None and s.field(cur, s.current_txn).settled
    if s.state in ("ASK_MORE_TXN", "REVIEW") and added:
        if s.state == "REVIEW":
            s.phase = "CASE"
        _advance(s, acts)
    elif s.state in ("GAP_FILL", "READBACK") and cur_settled:
        s.readback = None
        _advance(s, acts)
    elif s.state == "READBACK" and s.readback:
        _say_chunk(s, acts)
    elif s.state == "GAP_FILL" and cur:
        _ask_again(s, acts)
    elif s.state == "ASK_MORE_TXN":
        _speak(s, acts, "ASK_MORE_TXN")
    elif s.state == "REVIEW":
        _review(s, acts)


# ---------------------------------------------------------------- typed input
def _numpad(s: Session, acts: list[Action], ev: Event) -> None:
    name = ev.field or s.current_field
    if not name or name not in TXN_FIELDS + CASE_FIELDS:
        return
    txn = ev.txn_index if ev.txn_index is not None else (s.current_txn if s.current_txn is not None
                                                          else s.txn_cursor)
    if name in TXN_FIELDS and (not s.txns or not 0 <= txn < len(s.txns)):
        return
    f = s.field(name, txn)
    digits = re.sub(r"\D", "", ev.digits or "")
    rb = s.readback
    if rb and rb.field == name and rb.txn_index == (txn if name in TXN_FIELDS else None) \
            and rb.awaiting == "correct" and name in DIGIT_FIELDS and len(digits) == len(rb.chunks[rb.index]):
        # typed just the chunk being corrected
        rb.chunks[rb.index] = digits
        digits = "".join(rb.chunks)
    precision = None
    reason = ""
    if name == "amount":
        v_amt = V.validate_amount(int(digits) if digits else None)
        ok, value = v_amt.ok, v_amt.value
    elif name == "utr":
        v = V.validate_utr(digits)
        ok, value, reason = v.ok, v.value, v.reason
    elif name in ("suspect_phone", "victim_mobile"):
        v = V.validate_phone(digits)
        ok, value, reason = v.ok, v.value, v.reason
    else:
        ok, value, precision = _typed_text(name, ev.digits or "")
    if not ok:
        acts.append(Action(type="ShowNumpad", data={"field": name, "txn_index": txn, "error": "invalid"}))
        if is_asked(s, name, txn) and not _repair(s, name, txn):
            _give_up(s, acts, name, txn)  # typed wrong again and again: an officer checks it, the call goes on
            return
        if not _wrong_len_prompt(s, acts, name, reason):
            _speak(s, acts, "USE_NUMPAD" if name in DIGIT_FIELDS or name == "amount" else "DIDNT_CATCH")
        return
    if name == "utr" and _dup_utr_of(s, str(value), txn):
        s.state = "DUP_CHECK"
        s.current_field, s.current_txn, s.readback = "utr", txn, None
        s.dup_utr = str(value)
        _speak(s, acts, "DUP_UTR")
        return
    _set(f, value, status="confirmed", source="numpad", confidence="high",
         precision=precision or ("minute" if name == "datetime" and value else None))
    is_current = name == s.current_field and (name not in TXN_FIELDS or txn == s.current_txn)
    if is_current:
        s.readback = None
        s.show_numpad = False
        _advance(s, acts)
    elif s.state == "REVIEW":
        _update(s, acts)
        _review(s, acts)
    else:
        _update(s, acts)


def _skip(s: Session, acts: list[Action], ev: Event) -> None:
    if s.state == "NARRATIVE":
        # Skip during the story means "no story, just ask me the questions"
        _speak(s, acts, "SKIPPED")
        _narrative(s, acts, Event(type="AUDIO_TURN", candidates={}))
        return
    name = ev.field or s.current_field
    if s.state == "ASK_MORE_TXN" or name == "more_txn":
        s.phase = "CASE"
        _advance(s, acts)
        return
    if not name or name not in TXN_FIELDS + CASE_FIELDS:
        return
    txn = ev.txn_index if ev.txn_index is not None else s.current_txn
    if name in TXN_FIELDS and (txn is None or not 0 <= txn < len(s.txns)):
        return
    f = s.field(name, txn)
    if f.status != "confirmed":
        f.status = "skipped"
    is_current = name == s.current_field and (name not in TXN_FIELDS or txn == s.current_txn)
    if is_current:
        s.readback = None
        _speak(s, acts, "SKIPPED")
        _advance(s, acts)
    else:
        _update(s, acts)


def _button(s: Session, acts: list[Action], ev: Event) -> None:
    yes = ev.answer == "yes"
    if ev.field == "more_txn" and s.state == "ASK_MORE_TXN":
        if yes:
            _new_txn(s, acts)
        else:
            s.phase = "CASE"
            _advance(s, acts)
        return
    if ev.field == "review" and s.state == "REVIEW":
        if yes:
            _queue(s, acts)
        else:
            _speak(s, acts, "REVIEW_FIX")
        return
    if ev.field == "story" and s.state == "STORY_CHECK":
        _story_answer(s, acts, yes)
        return
    if ev.field == "dup_utr" and s.state == "DUP_CHECK":
        _dup_answer(s, acts, yes)
        return
    if not yes and s.state == "GAP_FILL" and ev.field == s.current_field and ev.field in KEYPAD_FIELDS:
        # 2 on a number question means "I don't know it"
        _skip(s, acts, Event(type="SKIP", field=ev.field, txn_index=s.current_txn))
        return
    if ev.field == "called_bank" and s.state == "GAP_FILL" and s.current_field == "called_bank":
        _set(s.fields["called_bank"], "yes" if yes else "no", status="confirmed", source="button",
             confidence="high")
        _advance(s, acts)
        return
    cur = s.readback
    if s.state != "READBACK" or cur is None or ev.field != cur.field or ev.chunk_index != cur.index \
            or (cur.txn_index is not None and ev.txn_index is not None and ev.txn_index != cur.txn_index):
        return  # stale button press
    if yes:
        _chunk_yes(s, acts)
    elif cur.awaiting == "correct":
        acts.append(Action(type="ShowNumpad", data={"field": cur.field, "txn_index": cur.txn_index,
                                                    "chunk_index": cur.index}))
        _speak(s, acts, "USE_NUMPAD")
    else:
        _readback_no(s, acts)


# ---------------------------------------------------------------- back
def _position(s: Session) -> tuple[object, ...]:
    """What the caller can see of the call. A re-asked question leaves it unchanged, so it is not a step."""
    rb = s.readback
    values = [(f.value, f.status) for t in s.txns for f in t.fields.values()]
    values += [(f.value, f.status) for f in s.fields.values()]
    return (s.state, s.phase, s.current_field, s.current_txn, (rb.index, rb.awaiting, rb.chunks) if rb else None, values)


def _reask(s: Session, acts: list[Action]) -> None:
    _update(s, acts)
    if s.state == "NARRATIVE":
        _speak(s, acts, "ASK_STORY")
    elif s.state == "GAP_FILL" and s.current_field:
        if s.show_numpad:
            acts.append(Action(type="ShowNumpad", data={"field": s.current_field, "txn_index": s.current_txn}))
        _ask_again(s, acts)
    elif s.state == "READBACK" and s.readback:
        rb = s.readback
        _say_chunk(s, acts)
        if rb.awaiting == "correct":
            acts.append(Action(type="ShowNumpad", data={"field": rb.field, "txn_index": rb.txn_index,
                                                        "chunk_index": rb.index}))
            _speak(s, acts, "CORRECT_CHUNK")
    elif s.state == "ASK_MORE_TXN":
        _speak(s, acts, "ASK_MORE_TXN")
    elif s.state == "DUP_CHECK":
        _speak(s, acts, "DUP_UTR")
    elif s.state == "STORY_CHECK":
        _story_check(s, acts)
    elif s.state == "REVIEW":
        _review(s, acts)


def _back(session: Session) -> tuple[Session, list[Action]]:
    """Return to the step before the last answer. A value goes back to how it was then, so a confirmed
    digit can only become unconfirmed or empty here, and the caller answers again."""
    s = session.model_copy(deep=True)
    acts: list[Action] = []
    if s.state in TERMINAL or not s.history:  # a packet that has been pushed is the operator's now
        return s, acts
    snapshot = s.history[-1]
    restored = Session.model_validate({**s.model_dump(include=KEPT_ON_BACK), **snapshot})
    restored.history = s.history[:-1]
    restored.last_active = time.time()
    _reask(restored, acts)
    return restored, acts


# ---------------------------------------------------------------- entry point
def next_state(session: Session, ev: Event) -> tuple[Session, list[Action]]:
    if ev.type == "BACK":
        return _back(session)
    s, acts = _step(session, ev)
    if ev.type in UNDOABLE and s.state not in TERMINAL and _position(s) != _position(session):
        s.history = [*session.history, session.model_dump(exclude=KEPT_ON_BACK)][-MAX_BACK_STEPS:]
    return s, acts


def _step(session: Session, ev: Event) -> tuple[Session, list[Action]]:
    s = session.model_copy(deep=True)
    acts: list[Action] = []
    s.last_active = time.time()
    settings = get_settings()

    if s.state in TERMINAL:
        if ev.type == "OPERATOR_TAKEOVER" and s.state.startswith("HANDOFF"):
            s.operator_claimed = True
        if s.state == "QUEUED":
            acts.append(Action(type="ShowSummary"))
        return s, acts

    if ev.type == "START":
        s.state = "NARRATIVE"
        _speak(s, acts, "OPENING")
        return s, acts
    if ev.type in ("HUMAN", "OPERATOR_TAKEOVER"):
        reason: HandoffReason = {"max_turns": "max_turns", "hangup": "caller_hung_up"}.get(ev.text, "caller_request")  # type: ignore[assignment]
        _handoff(s, acts, "HANDOFF_HUMAN", reason)
        if ev.type == "OPERATOR_TAKEOVER":
            s.operator_claimed = True
        return s, acts
    if ev.type == "SMS_PASTED":
        _apply_sms(s, acts, ev.text)
        return s, acts
    if ev.type == "SKIP":
        _skip(s, acts, ev)
        return s, acts
    if ev.type == "NUMPAD":
        _numpad(s, acts, ev)
        return s, acts
    if ev.type == "BUTTON":
        _button(s, acts, ev)
        return s, acts

    # AUDIO_TURN / TIMEOUT
    text = (ev.text or "").strip()
    if ev.type == "TIMEOUT" or not text:
        s.silence_count += 1
        if s.silence_count >= settings.SILENCE_HANDOFF_COUNT:
            _handoff(s, acts, "HANDOFF_HUMAN", "silence")
        else:
            _speak(s, acts, "SILENCE")
        return s, acts
    s.silence_count = 0
    s.turns += 1

    check = safety.check(f"{text} {ev.literal or ''}")
    if "SELF_HARM" in check.flags:
        s.transcripts.append(check.scrubbed_text)
        _handoff(s, acts, "HANDOFF_WELLBEING", "wellbeing")
        return s, acts
    if "NONFIN" in check.flags:
        s.transcripts.append(check.scrubbed_text)
        _handoff(s, acts, "HANDOFF_NONFIN", "non_financial")
        return s, acts
    if "SECRET" in check.flags or "ID" in check.flags:
        s.transcripts.append(check.scrubbed_text)
        prev = s.last_prompt_text
        _speak(s, acts, "NEVER_SHARE_OTP")
        if prev:
            _speak(s, acts, text=prev, speed="readback" if s.state == "READBACK" else "prompt")
        return s, acts
    s.transcripts.append(text)

    if yesno.classify(text).intent == "HUMAN":
        _handoff(s, acts, "HANDOFF_HUMAN", "caller_request")
        return s, acts
    if s.turns > settings.MAX_TURNS_PER_CALL:
        _handoff(s, acts, "HANDOFF_HUMAN", "max_turns")
        return s, acts

    if s.state in ("NARRATIVE", "OPENING", "CONSENT"):
        _narrative(s, acts, ev)
    elif s.state == "STORY_CHECK":
        yn = yesno.classify(text).intent
        if yn == "REPEAT":
            _story_check(s, acts)
        elif yn in ("YES", "NO", "CORRECTION"):
            _story_answer(s, acts, yn == "YES")
        elif not _not_understood(s, acts):
            _speak(s, acts, "CONFIRM_HINT")
            _story_check(s, acts)
    elif s.state == "GAP_FILL":
        _gap_answer(s, acts, text, ev.literal)
    elif s.state == "READBACK":
        _readback_answer(s, acts, text, ev.literal)
    elif s.state == "ASK_MORE_TXN":
        _more_txn_answer(s, acts, text)
    elif s.state == "DUP_CHECK":
        yn = yesno.classify(text).intent
        if yn in ("YES", "NO"):
            s.unknown_streak = 0
            _dup_answer(s, acts, yn == "YES")
        elif not _not_understood(s, acts):
            _speak(s, acts, "DUP_UTR")
    elif s.state == "REVIEW":
        yn = yesno.classify(text).intent
        if yn == "YES":
            _queue(s, acts)
        elif yn == "NO":
            s.unknown_streak = 0
            _speak(s, acts, "REVIEW_FIX")
        elif not _not_understood(s, acts):
            _review(s, acts)
    return s, acts

"""One call -> one Packet, rendered two ways:
A. Complaint Packet for the operator (CFCFRMS field order; copyable text + JSON).
B. Victim Summary for the caller (draft reference, transactions, total, next steps).

Forbidden PII never reaches a packet: the safety filter drops it before the FSM sees the text."""

from __future__ import annotations

import re
import secrets
from datetime import datetime
from typing import Any

from app.config import get_settings
from app.dialog import prompts
from app.dialog.models import CASE_FIELDS, TXN_FIELDS, FieldState, Packet, Session
from app.logging_utils import mask
from app.nlp.numbers import format_inr
from app.nlp.sms_parser import sms_datetime

FRAUD_LABELS = {
    "OTP_BANK_CALL": "OTP / bank impersonation",
    "UPI_COLLECT": "UPI collect / QR scam",
    "DIGITAL_ARREST": "Digital arrest / fake police",
    "INVESTMENT": "Investment / trading scam",
    "JOB_TASK": "Job / task scam",
    "LOAN_APP": "Loan app",
    "FAKE_CUSTOMER_CARE": "Fake customer care",
    "OTHER": "Other",
}
REASON_LABELS = {
    "caller_request": "caller asked for a person",
    "silence": "no speech heard",
    "max_turns": "call too long",
    "not_understood": "AI could not understand",
    "repairs_exhausted": "AI could not capture details",
    "non_financial": "non-financial case",
    "wellbeing": "WELLBEING — caller may be at risk",
    "caller_hung_up": "caller hung up mid-call",
}
CHANNEL_LABELS = {"phone": "experimental telephony"}
PART_OF_DAY = {9: "morning", 13: "afternoon", 18: "evening", 21: "night"}


_AMOUNTISH = re.compile(r"(?<![\w•])\d{1,3}(?:,\d{2,3})+(?:\.\d+)?(?!\w)|(?<![\w•])\d{4,}(?!\w)")


def mask_transcript(t: str) -> str:
    """Handoff transcripts are masked like logs, and bare figures ("50,000", "4306") too: the operator reads
    the numbers from the packet fields, where each one carries its source and status."""
    return _AMOUNTISH.sub("•••", mask(t))


def new_packet_id() -> str:
    return f"CD-DRAFT-{secrets.token_hex(2).upper()}"


def build(s: Session, status: str, reason: str | None = None, packet_id: str | None = None) -> Packet:
    ft = s.fields["fraud_type"].value or "OTHER"
    end = s.ended_at or s.last_active
    return Packet(
        id=packet_id or new_packet_id(), session_id=s.id, lang=s.lang, channel=s.channel,
        status=status,  # type: ignore[arg-type]
        handoff_reason=reason,  # type: ignore[arg-type]
        fraud_type=str(ft),
        txns=[{k: f.model_copy() for k, f in t.fields.items()} for t in s.txns
              if any(f.value is not None for f in t.fields.values())],
        fields={k: f.model_copy() for k, f in s.fields.items() if k != "fraud_type"},
        reported_txn_count=s.expected_txn_count or 0,
        transcript_masked=[mask_transcript(t) for t in s.transcripts] if status == "needs_human" else [],
        call_started_at=s.created_at, handled_s=round(end - s.created_at, 1),
    )


# ---------------------------------------------------------------- display helpers
def tag(f: FieldState) -> str:
    if f.value is None or f.status in ("skipped", "empty"):
        return ""
    if f.status in ("unconfirmed", "pending"):
        return "⚠ verify"
    if f.source == "sms":
        return "[sms]"
    if f.source == "numpad":
        return "[typed ✓]"
    if f.source == "operator":
        return "[operator]"
    t = "[voice ✓"
    if f.corrections:
        t += f" corrected {f.corrections}×"
    return t + "]"


def display_datetime(f: FieldState) -> str:
    dt = sms_datetime(str(f.value)) if f.value is not None else None
    if dt is None:
        return str(f.value) if f.value is not None else "—"
    approx = "" if f.source in ("sms", "numpad", "operator") and f.precision == "minute" else "~"
    date = dt.strftime("%d-%m-%Y")
    if f.precision == "day":
        return f"{date} (time not known)"
    if f.precision == "part_of_day" and dt.minute == 0 and dt.hour in PART_OF_DAY:
        return f"{date} {PART_OF_DAY[dt.hour]} (~{dt.strftime('%H:%M')})"
    return f"{date} {approx}{dt.strftime('%H:%M')}"


def display(f: FieldState | None) -> str:
    if f is None or f.value is None or f.status in ("skipped", "empty"):
        return "—"
    if f.name == "datetime":
        return display_datetime(f)
    return f.display()


def _cell(f: FieldState | None) -> str:
    if f is None:
        return "—"
    if f.value is None and f.status == "unconfirmed":
        return "⚠ verify"
    t = tag(f)
    return f"{display(f)} {t}".strip()


def _elapsed(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m} min {s} s" if m else f"{s} s"


def field_row(f: FieldState) -> dict[str, Any]:
    return {"value": f.value, "display": display(f), "status": f.status, "source": f.source,
            "confidence": f.confidence, "precision": f.precision, "corrections": f.corrections, "warn": f.warn,
            "verify": f.value is not None and f.status in ("unconfirmed", "pending")
            or (f.value is None and f.status == "unconfirmed")}


# ---------------------------------------------------------------- A. Complaint Packet
def render_text(p: Packet) -> str:
    app = get_settings().APP_NAME
    status = p.status if not p.handoff_reason else f"{p.status} ({REASON_LABELS.get(p.handoff_reason, p.handoff_reason)})"
    f = p.fields
    last4 = f.get("victim_account_last4")
    bank = display(f.get("victim_bank"))
    if last4 is not None and last4.value:
        bank += f"  (a/c last 4: {last4.value})"
    lines = [
        f"DRAFT — {p.id} — not filed. {app} is not affiliated with MHA, I4C, NCRP or TN Police.",
        f"{'Status':<14}: {status}",
        *([f"{'Channel':<14}: {CHANNEL_LABELS[p.channel]}"] if p.channel in CHANNEL_LABELS else []),
        f"{'Fraud type':<14}: {FRAUD_LABELS.get(p.fraud_type, p.fraud_type)}",
        f"{'Victim bank':<14}: {bank:<34} Payment mode: {display(f.get('payment_mode'))}",
        f"{'Called bank?':<14}: {display(f.get('called_bank'))}",
    ]
    for i, t in enumerate(p.txns):
        utr = t.get("utr")
        utr_cell = "UTR " + _cell(utr) if utr is not None and (utr.value is not None or utr.status == "unconfirmed") \
            else "UTR —"
        lines.append(f"{'Txn ' + str(i + 1):<14}: {_cell(t.get('amount'))} | {_cell(t.get('datetime'))} | {utr_cell}")
    if p.txns:
        lines.append(f"{'Total':<14}: {format_inr(p.total_amount())} ({len(p.txns)} transaction"
                     f"{'s' if len(p.txns) != 1 else ''})")
    if p.reported_txn_count > len(p.txns):
        lines.append(f"{'⚠ Incomplete':<14}: caller mentioned {p.reported_txn_count} transactions, "
                     f"{len(p.txns)} captured. Ask about the rest.")
    lines += [
        f"{'Suspect phone':<14}: {_cell(f.get('suspect_phone'))}",
        f"{'Suspect UPI':<14}: {_cell(f.get('suspect_upi')):<34} Suspect bank: {_cell(f.get('suspect_bank'))}",
        f"{'District':<14}: {_cell(f.get('district'))}",
        f"{'Victim':<14}: {_cell(f.get('victim_name'))} / {_cell(f.get('victim_mobile'))}",
    ]
    foot = f"Handled by AI in {_elapsed(p.handled_s)}" if p.status != "needs_human" and not p.handoff_reason \
        else f"Handed to an officer after {_elapsed(p.handled_s)} (simulated transfer)"
    last = p.last_debit_time()
    if last is not None:
        mins = int((p.call_started_at + p.handled_s - last) // 60)
        if mins >= 0:
            ago = f"{mins} min" if mins < 60 else f"{mins // 60} h {mins % 60} min"
            foot += f" · last debit ~{ago} before call end"
    lines.append(foot)
    return "\n".join(line.rstrip() for line in lines)


def to_json(p: Packet, *, with_transcript: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": p.id, "status": p.status, "handoff_reason": p.handoff_reason, "fraud_type": p.fraud_type,
        "fraud_label": FRAUD_LABELS.get(p.fraud_type, p.fraud_type), "lang": p.lang,
        "txns": [{k: field_row(t[k]) for k in TXN_FIELDS if k in t} for t in p.txns],
        "fields": {k: field_row(p.fields[k]) for k in CASE_FIELDS + ["victim_account_last4"] if k in p.fields},
        "total": p.total_amount(), "total_display": format_inr(p.total_amount()),
        "created_at": p.created_at, "handled_s": p.handled_s, "approval_latency_s": p.approval_latency_s,
        "last_debit_time": p.last_debit_time(), "reject_reason": p.reject_reason,
        "text": render_text(p), "draft": True,
    }
    if with_transcript:
        d["transcript"] = p.transcript_masked
    return d


# ---------------------------------------------------------------- B. Victim Summary
def next_steps(lang: str) -> list[dict[str, Any]]:
    demo = get_settings().DEMO_MODE
    return [{"id": pid, "text": prompts.text(pid, lang),
             "draft": demo and pid not in prompts.NEXT_STEPS_SOURCED} for pid in prompts.NEXT_STEPS]


def victim_summary(s: Session, packet_id: str | None) -> dict[str, Any]:
    amounts = [t.fields["amount"] for t in s.txns if t.fields["amount"].value is not None]
    total = sum(int(a.value) for a in amounts if isinstance(a.value, int))
    steps = next_steps(s.lang)
    en = s.lang == "en"
    head = (f"Draft reference: {packet_id or '—'} (not an NCRP acknowledgement)" if en else
            f"வரைவு எண்: {packet_id or '—'} (இது NCRP ஒப்புகை எண் இல்லை)")
    body = (f"{len(amounts)} transaction(s), total {format_inr(total)}" if en else
            f"{len(amounts)} பரிவர்த்தனை, மொத்தம் {format_inr(total)}")
    txt = [head, body, ""]
    for i, st in enumerate(steps, 1):
        txt.append(f"{i}. {st['text']}" + (" [draft guidance]" if st["draft"] else ""))
    txt.append("1930 · cybercrime.gov.in")
    return {"packet_id": packet_id, "n_txns": len(amounts), "total": total, "total_display": format_inr(total),
            "next_steps": steps, "text": "\n".join(txt), "handoff": s.handoff,
            "operator_claimed": s.operator_claimed, "generated_at": datetime.now().isoformat(timespec="seconds")}

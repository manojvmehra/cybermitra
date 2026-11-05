"""Pydantic models for call + packet state. Everything lives in memory."""

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

Lang = Literal["ta", "en"]
State = Literal["CONSENT", "OPENING", "NARRATIVE", "GAP_FILL", "READBACK", "ASK_MORE_TXN", "DUP_CHECK", "REVIEW",
                "QUEUED", "HANDOFF_HUMAN", "HANDOFF_NONFIN", "HANDOFF_WELLBEING", "END"]
Status = Literal["empty", "pending", "confirmed", "unconfirmed", "skipped"]
PacketStatus = Literal["ready_for_review", "needs_human", "claimed", "approved", "rejected"]
HandoffReason = Literal["caller_request", "silence", "max_turns", "not_understood", "repairs_exhausted",
                        "non_financial", "wellbeing", "caller_hung_up"]
Channel = Literal["web", "phone"]

# Per-transaction fields, asked in this order inside the transaction loop.
TXN_FIELDS = ["amount", "datetime", "utr"]
# Case fields, asked once after the last transaction (CFCFRMS order).
CASE_FIELDS = ["victim_bank", "payment_mode", "suspect_phone", "suspect_upi", "suspect_bank", "called_bank",
               "district", "victim_name", "victim_mobile"]
OPTIONAL_FIELDS = {"suspect_upi", "suspect_bank"}
DIGIT_FIELDS = {"utr": 12, "suspect_phone": 10, "victim_mobile": 10}
# Fields whose spoken answer is accepted without a read-back (the answer itself was yes/no).
NO_READBACK = {"called_bank"}
MAX_REPAIRS = 2
ALL_FIELDS = TXN_FIELDS + CASE_FIELDS


class FieldState(BaseModel):
    name: str
    value: str | int | None = None
    status: Status = "empty"
    source: str | None = None
    confidence: Literal["high", "low"] | None = None
    precision: str | None = None  # datetime only: minute | hour | part_of_day | day
    corrections: int = 0
    span_text: str = ""
    warn: str = ""

    def display(self) -> str:
        from app.nlp.numbers import format_inr

        if self.value is None:
            return "—"
        if self.name == "amount" and isinstance(self.value, int):
            return format_inr(self.value)
        if self.name in ("suspect_phone", "victim_mobile") and isinstance(self.value, str) and len(self.value) == 10:
            return f"{self.value[:5]} {self.value[5:]}"
        if self.name == "utr" and isinstance(self.value, str) and len(self.value) == 12:
            return f"{self.value[:4]} {self.value[4:8]} {self.value[8:]}"
        if self.name == "called_bank":
            return "Yes" if self.value == "yes" else "No" if self.value == "no" else str(self.value)
        return str(self.value)

    @property
    def settled(self) -> bool:
        return self.status in ("confirmed", "unconfirmed", "skipped")


def _txn_fields() -> dict[str, FieldState]:
    return {n: FieldState(name=n) for n in TXN_FIELDS}


class Txn(BaseModel):
    fields: dict[str, FieldState] = Field(default_factory=_txn_fields)

    @property
    def done(self) -> bool:
        return all(f.settled for f in self.fields.values())


class ReadbackCursor(BaseModel):
    field: str
    txn_index: int | None = None  # None for case fields
    chunks: list[str]
    index: int = 0
    awaiting: Literal["confirm", "correct"] = "confirm"
    unclear: int = 0  # unclear answers to the current chunk (re-asked without using a repair)


def _case_fields() -> dict[str, FieldState]:
    return {n: FieldState(name=n) for n in CASE_FIELDS + ["fraud_type", "victim_account_last4"]}


class Session(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    lang: Lang = "ta"
    channel: Channel = "web"
    state: State = "CONSENT"
    phase: Literal["TXN", "CASE"] = "TXN"
    txns: list[Txn] = Field(default_factory=list)
    txn_cursor: int = 0  # the transaction the loop is working on
    current_field: str | None = None
    current_txn: int | None = None
    readback: ReadbackCursor | None = None
    fields: dict[str, FieldState] = Field(default_factory=_case_fields)
    repair_attempts: dict[str, int] = Field(default_factory=dict)  # key: "field" or "field#txn"
    expected_txn_count: int | None = None
    dup_utr: str | None = None  # a UTR heard again, awaiting "is this the one you mentioned before?"
    silence_count: int = 0
    unknown_streak: int = 0
    gave_up: int = 0  # fields that ran out of repairs this call
    turns: int = 0  # non-empty spoken turns handled by the FSM
    api_turns: int = 0  # STT calls made for this session (rate limit)
    created_at: float = Field(default_factory=time.time)
    last_active: float = Field(default_factory=time.time)
    ended_at: float | None = None
    last_prompt_text: str = ""
    handoff: str | None = None
    handoff_reason: HandoffReason | None = None
    packet_id: str | None = None
    operator_claimed: bool = False
    show_numpad: bool = False
    transcripts: list[str] = Field(default_factory=list)  # in-memory only, never logged raw
    history: list[dict[str, Any]] = Field(default_factory=list)  # earlier steps for the Back button; memory only

    def elapsed_s(self) -> float:
        end = self.ended_at or time.time()
        return round(end - self.created_at, 1)

    def field(self, name: str, txn: int | None = None) -> FieldState:
        if name in TXN_FIELDS:
            return self.txns[self.txn_cursor if txn is None else txn].fields[name]
        return self.fields[name]


# ---------------------------------------------------------------- FSM events / actions
class Event(BaseModel):
    type: Literal["START", "AUDIO_TURN", "SMS_PASTED", "BUTTON", "NUMPAD", "SKIP", "BACK", "TIMEOUT", "HUMAN",
                  "OPERATOR_TAKEOVER"]
    text: str = ""
    literal: str | None = None
    field: str | None = None  # a field name, or "more_txn" / "review" / "dup_utr" for yes-no buttons
    txn_index: int | None = None
    chunk_index: int | None = None
    answer: Literal["yes", "no"] | None = None
    digits: str | None = None
    candidates: dict[str, Any] | None = None  # pre-computed narrative candidates (Evon merge)


class Action(BaseModel):
    type: Literal["SpeakPrompt", "ShowReadback", "UpdateFields", "ShowSummary", "ShowNumpad", "Handoff",
                  "PushPacket"]
    prompt_id: str | None = None
    text: str | None = None
    speed: Literal["prompt", "readback"] = "prompt"
    data: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------- packet (operator side)
class AuditEntry(BaseModel):
    at: float = Field(default_factory=time.time)
    packet_id: str
    event: str  # reorder | status | edit
    from_pos: int | None = None
    to_pos: int | None = None
    reason: str = ""


class Packet(BaseModel):
    id: str  # CM-DRAFT-XXXX
    session_id: str
    lang: Lang
    channel: Channel = "web"
    status: PacketStatus
    handoff_reason: HandoffReason | None = None
    fraud_type: str = "OTHER"
    txns: list[dict[str, FieldState]] = Field(default_factory=list)
    fields: dict[str, FieldState] = Field(default_factory=dict)
    reported_txn_count: int = 0  # debits the caller mentioned, which can exceed the ones captured here
    transcript_masked: list[str] = Field(default_factory=list)  # handoffs only
    created_at: float = Field(default_factory=time.time)
    call_started_at: float = 0
    handled_s: float = 0
    opened_at: float | None = None
    decided_at: float | None = None
    approval_latency_s: float | None = None
    reject_reason: str = ""
    operator_edits: int = 0

    def last_debit_time(self) -> float | None:
        """Latest *confirmed* debit time as a timestamp. Unconfirmed times never count."""
        from app.nlp.sms_parser import sms_datetime

        best: float | None = None
        for t in self.txns:
            f = t.get("datetime")
            if f is None or f.status != "confirmed" or not isinstance(f.value, str):
                continue
            dt = sms_datetime(f.value)
            if dt is not None:
                ts = dt.timestamp()
                best = ts if best is None else max(best, ts)
        return best

    def total_amount(self) -> int:
        return sum(int(t["amount"].value) for t in self.txns
                   if t.get("amount") is not None and isinstance(t["amount"].value, int))

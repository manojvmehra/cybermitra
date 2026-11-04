from typing import Any, Literal

from pydantic import BaseModel, Field


class CreateSession(BaseModel):
    lang: Literal["ta", "en"] = "ta"
    consent: bool


class SmsIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


FieldName = Literal["amount", "datetime", "utr", "victim_bank", "payment_mode", "suspect_phone", "suspect_upi",
                    "suspect_bank", "called_bank", "district", "victim_name", "victim_mobile"]
# yes/no questions answered by a button rather than a read-back chunk
ConfirmTarget = Literal["amount", "datetime", "utr", "victim_bank", "payment_mode", "suspect_phone", "suspect_upi",
                        "suspect_bank", "called_bank", "district", "victim_name", "victim_mobile",
                        "more_txn", "review", "dup_utr"]


class ConfirmIn(BaseModel):
    field: ConfirmTarget
    txn_index: int | None = Field(default=None, ge=0, le=64)
    chunk_index: int = Field(default=0, ge=0, le=64)
    answer: Literal["yes", "no"]


class NumpadIn(BaseModel):
    """Typed input. Digits for number fields; short free text for bank / date / UPI / name / district."""
    field: FieldName
    txn_index: int | None = Field(default=None, ge=0, le=64)
    digits: str = Field(min_length=1, max_length=120)


class SkipIn(BaseModel):
    field: FieldName | Literal["more_txn"]
    txn_index: int | None = Field(default=None, ge=0, le=64)


class PromptOut(BaseModel):
    text: str = ""
    audio_url: str | None = None
    audio_urls: list[str] = []


class TurnResponse(BaseModel):
    session_id: str
    state: str
    current_field: str | None = None
    current_txn: int | None = None
    ask: str | None = None  # a yes/no question with buttons: more_txn | review | dup_utr | called_bank
    transcript: str | None = None
    txns: list[dict[str, Any]]
    fields: dict[str, dict[str, Any]]
    readback: dict[str, Any] | None = None
    numpad: dict[str, Any] | None = None
    can_back: bool = False
    prompt: PromptOut
    handoff: str | None = None
    packet_id: str | None = None
    summary: dict[str, Any] | None = None
    elapsed_s: float
    demo_banner: str | None = None
    error: str | None = None


# ---------------------------------------------------------------- operator
class EditIn(BaseModel):
    field: Literal["amount", "datetime", "utr", "victim_bank", "payment_mode", "suspect_phone", "suspect_upi",
                   "suspect_bank", "called_bank", "district", "victim_name", "victim_mobile",
                   "victim_account_last4"]
    txn_index: int | None = Field(default=None, ge=0, le=64)
    value: str = Field(min_length=1, max_length=120)


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=200)

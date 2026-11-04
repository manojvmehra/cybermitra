"""Field validators. Each returns a Validation with a normalised value or a reason code."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class Validation:
    ok: bool
    value: str | int | None = None
    reason: str = ""
    warn: str = ""
    extra_confirm: bool = False


MAX_AMOUNT = 10_00_00_000
HIGH_AMOUNT = 10_00_000
UPI_RE = re.compile(r"^[\w.\-]{2,256}@[a-zA-Z]{2,64}$")


def validate_phone(digits: str) -> Validation:
    d = re.sub(r"\D", "", digits or "")
    if len(d) == 13 and d.startswith("091"):
        d = d[3:]
    elif len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    if len(d) != 10:
        return Validation(False, d, reason=f"phone_len_{len(d)}")
    if d[0] not in "6789":
        return Validation(False, d, reason="phone_prefix")
    return Validation(True, d)


def validate_utr(digits: str) -> Validation:
    d = re.sub(r"\D", "", digits or "")
    if len(d) != 12:
        return Validation(False, d, reason=f"utr_len_{len(d)}")
    return Validation(True, d)


def validate_upi(vpa: str) -> Validation:
    v = (vpa or "").strip().lower().replace(" ", "")
    if not UPI_RE.match(v):
        return Validation(False, v, reason="upi_format")
    return Validation(True, v)


def validate_amount(n: int | None) -> Validation:
    if n is None:
        return Validation(False, None, reason="amount_missing")
    if n < 1:
        return Validation(False, n, reason="amount_low")
    if n > MAX_AMOUNT:
        return Validation(False, n, reason="amount_high")
    return Validation(True, n, extra_confirm=n > HIGH_AMOUNT)


def validate_datetime(dt: datetime | None, now: datetime | None = None) -> Validation:
    now = now or datetime.now()
    if dt is None:
        return Validation(False, None, reason="datetime_missing")
    if dt > now + timedelta(minutes=5):
        return Validation(False, dt.strftime("%d-%m-%Y %H:%M"), reason="datetime_future")
    warn = "older_than_7_days" if now - dt > timedelta(days=7) else ""
    return Validation(True, dt.strftime("%d-%m-%Y %H:%M"), warn=warn)

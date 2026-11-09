"""Render the plain-text 1930 Call Card (copyable, ≤ ~14 lines)."""

from app.config import get_settings
from app.dialog.models import FieldState, Session

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

ROWS = [("Amount", "amount"), ("Bank", "bank"), ("Date/time", "datetime"), ("UTR/Ref", "utr"),
        ("Suspect ph", "suspect_phone"), ("Suspect UPI", "suspect_upi"), ("District", "district"),
        ("Your name", "victim_name"), ("Your mobile", "victim_mobile")]


def _tag(f: FieldState) -> str:
    if f.value is None or f.status in ("skipped", "empty"):
        return ""
    if f.status == "unconfirmed":
        return "⚠ verify"
    if f.source == "sms":
        return "[sms]"
    if f.source == "numpad":
        return "[typed ✓]"
    tag = "[voice ✓"
    if f.corrections:
        tag += f" corrected {f.corrections}×"
    return tag + "]"


def _display(f: FieldState) -> str:
    if f.value is None or f.status in ("skipped", "empty"):
        return "—"
    d = f.display()
    if f.name == "datetime" and f.source != "sms" and d.endswith(":00"):
        date, _, time = d.partition(" ")
        d = f"{date} ~{time}"
    return d


def _elapsed(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m} min {s} s" if m else f"{s} s"


def render(session: Session) -> str:
    app = get_settings().APP_NAME
    ft = session.fields["fraud_type"].value or "OTHER"
    lines = [f"DRAFT — not filed. {app} is not affiliated with MHA, I4C, NCRP or TN Police.",
             f"{'Fraud type':<11}: {FRAUD_LABELS.get(str(ft), str(ft))}"]
    for label, key in ROWS:
        f = session.fields[key]
        val = _display(f)
        tag = _tag(f)
        lines.append(f"{label:<11}: {val:<18} {tag}".rstrip())
    last4 = session.fields["victim_account_last4"]
    if last4.value:
        lines.append(f"{'Your a/c':<11}: ending {last4.value}  [sms]")
    lines.append("Call 1930 now. Read these lines to the officer. Also file at cybercrime.gov.in")
    lines.append(f"Prepared in {_elapsed(session.elapsed_s())}")
    return "\n".join(lines)

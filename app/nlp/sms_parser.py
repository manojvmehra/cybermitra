"""Exact extraction from a pasted bank / UPI SMS. Zero API calls."""

import re
from dataclasses import dataclass
from datetime import datetime

from app.nlp.lexicon_ta import BANK_ALIASES


@dataclass
class SmsField:
    value: str | int
    raw_span: str
    source: str = "sms"
    confidence: str = "high"


_REF = re.compile(
    r"(?:UTR|RRN|UPI\s*Ref(?:\.|erence)?(?:\s*No\.?)?|Ref(?:erence)?\s*(?:No\.?|Number|#)?|Txn\s*(?:ID|No\.?)|"
    r"Transaction\s*(?:ID|Ref)|IMPS\s*Ref(?:\s*No\.?)?)\s*[:#\-]?\s*(?:is\s*)?(\d{12})(?!\d)",
    re.IGNORECASE,
)
_ANY12 = re.compile(r"(?<!\d)(\d{12})(?!\d)")
_AMOUNT = re.compile(r"(?:Rs\.?|INR|₹)\s?([\d,]+(?:\.\d{1,2})?)", re.IGNORECASE)
_DEBIT_CUE = re.compile(r"debited|sent|paid|transferred|withdrawn|deducted|spent|dr\b|debit", re.IGNORECASE)
_VPA = re.compile(r"(?<![\w.\-])([\w.\-]{2,}@[a-zA-Z]{2,})(?![\w.\-]*\.[a-z]{2,})")
_ACCT = re.compile(r"(?:A/?c|Acct|Account|a/c no\.?)\s*(?:No\.?)?\s*[:\-]?\s*(?:[Xx*]+|\.\.)?\s*(\d{3,6})\b",
                   re.IGNORECASE)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_D1 = re.compile(r"(?<!\d)(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})(?!\d)")
_D2 = re.compile(r"(?<!\d)(\d{1,2})[-\s]?(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[-\s,]?(\d{2,4})",
                 re.IGNORECASE)
_D3 = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_TIME = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?\s*(AM|PM|am|pm)?")

_SENDER_BANK = {
    "SBI": ["sbi", "sbiinb", "sbiupi", "state bank"],
    "HDFC": ["hdfc"],
    "ICICI": ["icici"],
    "Axis Bank": ["axis"],
    "Canara Bank": ["canara", "canbnk"],
    "Indian Overseas Bank": ["iob", "indian overseas"],
    "Indian Bank": ["indian bank", "indbnk"],
    "Kotak": ["kotak"],
    "Bank of Baroda": ["baroda", "bob"],
    "PNB": ["pnb", "punjab national"],
    "Union Bank": ["union bank", "unionb"],
}


def _year(y: str) -> int:
    n = int(y)
    return n + 2000 if n < 100 else n


def _parse_date(text: str) -> tuple[str, str] | None:
    m = _D3.search(text)
    if m:
        return f"{int(m.group(3)):02d}-{int(m.group(2)):02d}-{int(m.group(1))}", m.group(0)
    m = _D2.search(text)
    if m:
        return f"{int(m.group(1)):02d}-{_MONTHS[m.group(2)[:3].lower()]:02d}-{_year(m.group(3))}", m.group(0)
    for m in _D1.finditer(text):
        d, mo, y = int(m.group(1)), int(m.group(2)), _year(m.group(3))
        if 1 <= d <= 31 and 1 <= mo <= 12:
            return f"{d:02d}-{mo:02d}-{y}", m.group(0)
    return None


def _parse_time(text: str) -> tuple[str, str] | None:
    m = _TIME.search(text)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    ap = (m.group(4) or "").lower()
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}", m.group(0)


def _bank(text: str) -> tuple[str, str] | None:
    low = text.lower()
    for canon, keys in _SENDER_BANK.items():
        for k in keys:
            if re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", low):
                return canon, k
    for canon, aliases in BANK_ALIASES.items():
        for a in aliases:
            if a.isascii() and len(a) > 3 and a in low:
                return canon, a
    return None


def _is_balance(text: str, start: int) -> bool:
    return bool(re.search(r"(?:bal|balance|avl|available)\.?\s*[:\-]?\s*$", text[max(0, start - 20):start], re.I))


def parse_sms(text: str) -> dict[str, SmsField]:
    out: dict[str, SmsField] = {}
    if not text or not text.strip():
        return out

    m = _REF.search(text)
    if m:
        out["utr"] = SmsField(m.group(1), m.group(0))
    else:
        cands = [c for c in _ANY12.findall(text)]
        if len(cands) == 1:
            out["utr"] = SmsField(cands[0], cands[0], confidence="medium")

    amounts = list(_AMOUNT.finditer(text))
    chosen = None
    for am in amounts:
        window = text[max(0, am.start() - 40): am.end() + 40]
        if _DEBIT_CUE.search(window) and not _is_balance(text, am.start()):
            chosen = am
            break
    if chosen is None and amounts:
        # first amount that is not an available-balance figure
        for am in amounts:
            if not _is_balance(text, am.start()):
                chosen = am
                break
    if chosen:
        val = float(chosen.group(1).replace(",", "").rstrip("."))
        if val >= 1:
            out["amount"] = SmsField(int(val), chosen.group(0))

    b = _bank(text)
    if b:
        out["bank"] = SmsField(b[0], b[1])

    d = _parse_date(text)
    t = _parse_time(text)
    if d or t:
        value = " ".join(x for x in [d[0] if d else "", t[0] if t else ""] if x)
        raw = " ".join(x for x in [d[1] if d else "", t[1] if t else ""] if x)
        out["datetime"] = SmsField(value, raw)

    for vm in _VPA.finditer(text):
        vpa = vm.group(1)
        if "." in vpa.split("@")[1]:
            continue  # e-mail address, not a VPA
        out["suspect_upi"] = SmsField(vpa.lower(), vpa)
        break

    acct = _ACCT.search(text)
    if acct:
        out["victim_account_last4"] = SmsField(acct.group(1)[-4:], "A/c ••" + acct.group(1)[-4:])
    return out


_DEBIT_START = re.compile(r"(?i)(?:debited|sent|paid|transferred|withdrawn|deducted)")
_SENTENCE_END = re.compile(r"\n|(?<!Rs)(?<!INR)\.\s+(?=[A-Z])|\s-[A-Z]{2,10}\b\s*")


def split_sms(text: str) -> list[str]:
    """Several SMS pasted at once -> one string each. Split on blank lines; a single block that
    reports more than one debit is split before each later sentence carrying a debit cue."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text or "") if b.strip()]
    out: list[str] = []
    for b in blocks:
        hits = [m.start() for m in _DEBIT_START.finditer(b)]
        if len(hits) <= 1 or len(_AMOUNT.findall(b)) < 2:
            out.append(b)
            continue
        # cut at the line / sentence start before each debit cue after the first ("Rs. 500" is not a sentence end)
        bounds = [m.end() for m in _SENTENCE_END.finditer(b)]
        cuts = [0]
        for h in hits[1:]:
            prev = max([x for x in bounds if x <= h], default=0)
            if prev > cuts[-1]:
                cuts.append(prev)
        out += [b[i:j].strip() for i, j in zip(cuts, cuts[1:] + [len(b)], strict=False) if b[i:j].strip()]
    return out


def parse_sms_multi(text: str) -> list[dict[str, SmsField]]:
    """One dict per SMS (= one transaction). SMS that yield nothing are dropped."""
    return [p for p in (parse_sms(t) for t in split_sms(text)) if p]


def sms_datetime(value: str) -> datetime | None:
    for fmt in ("%d-%m-%Y %H:%M", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None

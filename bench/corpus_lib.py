"""Shared by the bench scripts: the per-call manifest and per-clip scoring.

Manifest row (one per call, see bench/make_manifest.py):

    {"call_id": "s1_spk1", "script_id": "S1_OTP_BANK", "speaker": "spk1", "improvised": false,
     "reference_time": "2026-11-05T12:00",
     "turns": [{"clip_id": "s1_spk1_narrative", "slot": "narrative", "truth": {"amounts": [40000, 10000]}},
               {"clip_id": "s1_spk1_utr_1", "slot": "utr", "txn": 0, "truth": "430619827418"},
               {"clip_id": "s1_spk1_no", "slot": "no", "truth": "NO"}],
     "call_truth": {"txns": [{"amount": 40000, "utr": "430619827418"}], "victim_bank": "SBI"}}

`reference_time` is when the caller is pretending to speak, so "nethu" (yesterday) has a fixed meaning.
Older flat rows ({"clip_id", "field_truth"}) load as a call with one narrative clip.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.dialog.models import ALL_FIELDS, DIGIT_FIELDS
from app.dialog.state_machine import _parse_field
from app.nlp import timeparse, yesno
from app.nlp.yesno import YesNo

INTENT_SLOTS = {"yes", "no", "correction"}
VALID_SLOTS = {"narrative", *ALL_FIELDS, *INTENT_SLOTS}
NUMERIC_SLOTS = {"amount", "utr", "suspect_phone", "victim_mobile"}
# how far a spoken time may be from the truth and still match, given how precisely it was said
TOLERANCE = {"minute": timedelta(minutes=5), "hour": timedelta(minutes=59), "part_of_day": timedelta(hours=3)}


@dataclass
class Call:
    call_id: str
    script_id: str | None = None
    speaker: str | None = None
    synthetic_tts: bool = False
    improvised: bool = False
    reference_time: datetime | None = None
    turns: list[dict[str, Any]] = field(default_factory=list)
    truth: dict[str, Any] = field(default_factory=dict)

    @property
    def narrative(self) -> dict[str, Any] | None:
        return next((t for t in self.turns if t["slot"] == "narrative"), None)


def _call_from_row(row: dict[str, Any]) -> Call:
    if "turns" not in row:  # flat row: one clip that tells the whole story
        truth = row.get("field_truth", {})
        return Call(row["clip_id"], row.get("script_id"), row.get("speaker"), bool(row.get("synthetic_tts")),
                    turns=[{"clip_id": row["clip_id"], "slot": "narrative", "truth": truth}], truth=truth)
    ref = row.get("reference_time")
    return Call(row["call_id"], row.get("script_id"), row.get("speaker"), bool(row.get("synthetic_tts")),
                bool(row.get("improvised")), datetime.fromisoformat(ref) if ref else None, row["turns"],
                row.get("call_truth", {}))


def load_calls(path: Path) -> list[Call]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [_call_from_row(json.loads(x)) for x in lines if x.strip() and not x.startswith("//")]


def manifest_problems(calls: list[Call]) -> list[str]:
    """Mistakes that would silently corrupt a score. Empty list means the manifest is usable."""
    out: list[str] = []
    seen: set[str] = set()
    for c in calls:
        if c.narrative is None:
            out.append(f"{c.call_id}: no narrative clip")
        for t in c.turns:
            cid, slot = t.get("clip_id"), t.get("slot")
            if cid in seen:
                out.append(f"{cid}: clip used twice")
            seen.add(cid)
            if slot not in VALID_SLOTS:
                out.append(f"{cid}: unknown slot {slot!r}")
            want = DIGIT_FIELDS.get(slot or "")
            truth = t.get("truth")
            if want and not (isinstance(truth, str) and truth.isdigit() and len(truth) == want):
                out.append(f"{cid}: {slot} truth must be {want} digits")
            if slot == "amount" and not isinstance(truth, int):
                out.append(f"{cid}: amount truth must be an integer")
            if slot == "datetime" and c.reference_time is None:
                out.append(f"{cid}: a time clip needs reference_time on its call")
    return out


def within_precision(got: str | None, truth: str, precision: str | None) -> bool:
    """A spoken time matches if it is right to the precision it was said with ("nethu" is right for any hour)."""
    if got is None:
        return False
    a, b = datetime.strptime(got, timeparse.FMT), datetime.strptime(truth, timeparse.FMT)
    if precision == "day":
        return a.date() == b.date()
    return abs(a - b) <= TOLERANCE.get(precision or "", timedelta(0))


def _digits_match(yn: YesNo, truth: Any) -> bool:
    return not isinstance(truth, dict) or "digits" not in truth or yn.digits == truth["digits"]


def score_slot(slot: str, truth: Any, text: str, literal: str | None, now: datetime | None) -> dict[str, Any]:
    """Score one answer clip the way a live call reads it: the slot is known from the question."""
    if slot in INTENT_SLOTS or slot == "called_bank":
        yn = yesno.classify(text)
        if slot == "called_bank":
            got: Any = {"YES": "yes", "NO": "no"}.get(yn.intent)
            return {"truth": truth, "got": got, "exact": got == truth}
        want = truth["intent"] if isinstance(truth, dict) else truth
        return {"truth": truth, "got": yn.intent, "exact": yn.intent == want and _digits_match(yn, truth)}
    p = _parse_field(slot, text, literal, now)
    if slot == "datetime":
        exact = within_precision(p.value if isinstance(p.value, str) else None, truth, p.precision)
    elif isinstance(truth, str) and isinstance(p.value, str):
        exact = p.value.casefold() == truth.casefold()
    else:
        exact = p.value == truth
    return {"truth": truth, "got": p.value, "exact": exact, "confidence": p.confidence or None,
            "source": p.source or None, "method": p.source or None, "precision": p.precision}

"""In-memory packet store: status transitions, operator edits, fair ordering and an audit log.

Approve / reject only change a status. Nothing here makes a network call or submits anywhere."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime

from app.config import get_settings
from app.dialog.models import TXN_FIELDS, AuditEntry, FieldState, Packet
from app.logging_utils import log
from app.nlp import extractor as X
from app.nlp import timeparse as T
from app.nlp import validators as V
from app.queue import priority

logger = logging.getLogger("queue")
AUDIT_MAX = 500
EDITABLE = {"ready_for_review", "claimed"}
TRANSITIONS = {
    "ready_for_review": {"approved", "rejected"},
    "needs_human": {"claimed"},
    "claimed": {"approved", "rejected"},
}


class TransitionError(Exception):
    """An operator action that the packet's status does not allow (HTTP 409)."""


class EditError(Exception):
    """An operator edit that fails validation (HTTP 422)."""


def validate_edit(field: str, value: str) -> tuple[str | int, str | None]:
    """-> (value, precision). Same validators as the call itself."""
    raw = (value or "").strip()
    digits = re.sub(r"\D", "", raw)
    if field == "amount":
        v = V.validate_amount(int(digits) if digits else None)
    elif field == "utr":
        v = V.validate_utr(digits)
    elif field in ("suspect_phone", "victim_mobile"):
        v = V.validate_phone(digits)
    elif field == "suspect_upi":
        v = V.validate_upi(raw)
    elif field == "datetime":
        tr = T.parse_time(raw)
        if tr.value is None:
            raise EditError("datetime: use dd-mm-yyyy hh:mm, not in the future")
        return tr.value.strftime(T.FMT), tr.precision
    elif field == "called_bank":
        if raw.lower() not in ("yes", "no"):
            raise EditError("called_bank: yes or no")
        return raw.lower(), None
    elif field in ("victim_bank", "suspect_bank"):
        b = X.find_bank(raw)
        if not raw:
            raise EditError(f"{field}: empty")
        return (b[0] if b else raw[:60]), None
    elif field in ("district", "victim_name", "payment_mode", "victim_account_last4"):
        if not raw:
            raise EditError(f"{field}: empty")
        if field == "victim_account_last4":
            if not re.fullmatch(r"\d{4}", raw):
                raise EditError("victim_account_last4: exactly 4 digits")
            return raw, None
        if field == "district":
            return X.find_district(raw) or raw[:60], None
        return raw[:60], None
    else:
        raise EditError(f"unknown field {field}")
    if not v.ok or v.value is None:
        raise EditError(f"{field}: {v.reason or 'invalid'}")
    return v.value, None


class QueueStore:
    def __init__(self) -> None:
        self.packets: dict[str, Packet] = {}
        self.audit: list[AuditEntry] = []
        self._review_pos: dict[str, int] = {}
        self._handoff_pos: dict[str, int] = {}

    def reset(self) -> None:
        self.packets.clear()
        self.audit.clear()
        self._review_pos.clear()
        self._handoff_pos.clear()

    # ------------------------------------------------------------ audit + order
    def _audit(self, e: AuditEntry) -> AuditEntry:
        self.audit.append(e)
        del self.audit[:-AUDIT_MAX]
        log(logger, "queue audit", packet=e.packet_id, event=e.event, frm=e.from_pos, to=e.to_pos, reason=e.reason)
        return e

    def review(self, now: float | None = None) -> list[tuple[Packet, str]]:
        items = [p for p in self.packets.values() if p.status == "ready_for_review"]
        return priority.review_order(items, now or time.time(), get_settings().QUEUE_MAX_WAIT_S)

    def handoffs(self) -> list[tuple[Packet, str]]:
        return priority.handoff_order([p for p in self.packets.values() if p.status in ("needs_human", "claimed")])

    def reorder(self, now: float | None = None) -> list[AuditEntry]:
        """Recompute both orders; audit every position change (with the item's placement reason)."""
        out: list[AuditEntry] = []
        for order, prev in ((self.review(now), self._review_pos), (self.handoffs(), self._handoff_pos)):
            new = {p.id: i for i, (p, _) in enumerate(order)}
            for p, reason in order:
                old = prev.get(p.id)
                if old != new[p.id]:
                    out.append(self._audit(AuditEntry(packet_id=p.id, event="reorder", from_pos=old,
                                                      to_pos=new[p.id], reason=reason)))
            prev.clear()
            prev.update(new)
        return out

    def reasons(self) -> dict[str, str]:
        return {p.id: r for p, r in self.review() + self.handoffs()}

    # ------------------------------------------------------------ lifecycle
    def add(self, p: Packet) -> list[AuditEntry]:
        self.packets[p.id] = p
        self._audit(AuditEntry(packet_id=p.id, event="status", reason=f"created: {p.status}"))
        return self.reorder()

    def get(self, pid: str) -> Packet | None:
        return self.packets.get(pid)

    def by_session(self, sid: str) -> Packet | None:
        return next((p for p in self.packets.values() if p.session_id == sid), None)

    def open(self, pid: str) -> Packet:
        p = self._must(pid)
        if p.opened_at is None:
            p.opened_at = time.time()
        return p

    def _must(self, pid: str) -> Packet:
        p = self.packets.get(pid)
        if p is None:
            raise KeyError(pid)
        return p

    def _move(self, p: Packet, to: str, reason: str = "") -> None:
        if to not in TRANSITIONS.get(p.status, set()):
            raise TransitionError(f"{p.status} -> {to} not allowed")
        self._audit(AuditEntry(packet_id=p.id, event="status", reason=f"{p.status} -> {to}" +
                               (f": {reason}" if reason else "")))
        p.status = to  # type: ignore[assignment]

    def claim(self, pid: str) -> Packet:
        p = self._must(pid)
        self._move(p, "claimed")
        if p.opened_at is None:
            p.opened_at = time.time()
        return p

    def approve(self, pid: str) -> Packet:
        p = self._must(pid)
        self._move(p, "approved")
        p.decided_at = time.time()
        p.approval_latency_s = round(p.decided_at - (p.opened_at or p.created_at), 1)
        return p

    def reject(self, pid: str, reason: str) -> Packet:
        p = self._must(pid)
        self._move(p, "rejected", "operator reason given")
        p.decided_at = time.time()
        p.reject_reason = reason[:200]
        return p

    def edit(self, pid: str, field: str, value: str, txn_index: int | None = None) -> Packet:
        p = self._must(pid)
        if p.status not in EDITABLE:
            raise TransitionError(f"cannot edit a packet in status {p.status}" +
                                  (" (claim it first)" if p.status == "needs_human" else ""))
        val, precision = validate_edit(field, value)
        if field in TXN_FIELDS:
            if txn_index is None or not 0 <= txn_index <= len(p.txns):
                raise EditError("txn_index out of range")
            if txn_index == len(p.txns):  # operator adds a transaction the caller missed
                p.txns.append({k: FieldState(name=k) for k in TXN_FIELDS})
            f = p.txns[txn_index][field]
        else:
            f = p.fields.setdefault(field, FieldState(name=field))
        f.value = val
        f.status = "confirmed"
        f.source = "operator"
        f.confidence = "high"
        f.precision = precision if field == "datetime" else f.precision
        p.operator_edits += 1
        where = f" txn {txn_index + 1}" if field in TXN_FIELDS and txn_index is not None else ""
        self._audit(AuditEntry(packet_id=p.id, event="edit", reason=f"operator edited {field}{where}"))
        return p

    def sweep(self, now: float | None = None) -> None:
        now = now or time.time()
        ttl = get_settings().PACKET_TTL_S
        for pid in [k for k, p in self.packets.items() if now - p.created_at > ttl]:
            self.packets.pop(pid, None)

    # ------------------------------------------------------------ metrics (no PII)
    def metrics(self) -> dict[str, object]:
        ps = list(self.packets.values())
        by_ai = [p for p in ps if p.handoff_reason is None]
        reasons: dict[str, int] = {}
        for p in ps:
            if p.handoff_reason:
                reasons[p.handoff_reason] = reasons.get(p.handoff_reason, 0) + 1
        lat = sorted(p.approval_latency_s for p in ps if p.approval_latency_s is not None)
        aht = sorted(p.handled_s for p in by_ai)
        return {
            "calls_total": len(ps), "calls_handled_by_ai": len(by_ai),
            "containment_rate": round(len(by_ai) / len(ps), 3) if ps else None,
            "handoffs": sum(reasons.values()), "handoffs_by_reason": reasons,
            "median_handling_s": _median(aht), "median_approval_s": _median(lat),
            "approved": sum(p.status == "approved" for p in ps), "rejected": sum(p.status == "rejected" for p in ps),
            "since": datetime.fromtimestamp(min((p.created_at for p in ps), default=time.time())).isoformat(
                timespec="seconds"),
        }


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    m = len(xs) // 2
    return round(xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2, 1)


store = QueueStore()

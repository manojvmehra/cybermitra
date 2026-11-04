"""Operator review queue. Every route needs the X-Operator-Token header.

Approve and reject change a packet's status and nothing else: no outbound call, no submission."""

import secrets
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse

from app.api import routes_caller
from app.api.events import bus
from app.api.schemas import EditIn, RejectIn
from app.config import get_settings
from app.dialog import packet as P
from app.dialog.models import Event, Packet
from app.dialog.state_machine import next_state
from app.queue.store import EditError, TransitionError, store


def require_operator(x_operator_token: str = Header(default="")) -> None:
    token = get_settings().OPERATOR_TOKEN
    if not token:
        raise HTTPException(503, "operator API disabled: set OPERATOR_TOKEN")
    if not secrets.compare_digest(x_operator_token.encode(), token.encode()):
        raise HTTPException(401, "operator token required")


router = APIRouter(dependencies=[Depends(require_operator)])


def _item(p: Packet, pos: int, reason: str, now: float) -> dict:
    return {"id": p.id, "pos": pos, "status": p.status, "handoff_reason": p.handoff_reason,
            "reason_label": P.REASON_LABELS.get(p.handoff_reason or "", ""), "why_here": reason,
            "fraud_label": P.FRAUD_LABELS.get(p.fraud_type, p.fraud_type), "n_txns": len(p.txns),
            "waiting_s": round(now - p.created_at), "created_at": p.created_at,
            "has_verify": any(r["verify"] for r in _rows(p)), "lang": p.lang,
            "channel_label": P.CHANNEL_LABELS.get(p.channel, "")}


def _rows(p: Packet) -> list[dict]:
    return [P.field_row(f) for t in p.txns for f in t.values()] + [P.field_row(f) for f in p.fields.values()]


def _packet(pid: str) -> Packet:
    p = store.get(pid)
    if p is None:
        raise HTTPException(404, "packet not found")
    return p


def _changed(p: Packet) -> dict:
    moved = store.reorder()
    bus.publish("packet_updated", {"id": p.id, "status": p.status})
    if moved:
        bus.publish("queue_reordered", {"changes": [e.model_dump() for e in moved]})
    return P.to_json(p, with_transcript=p.handoff_reason is not None)


@router.get("/api/operator/queue")
async def queue() -> dict:
    now = time.time()
    store.sweep(now)
    moved = store.reorder(now)  # time passing can make an item overdue
    if moved:
        bus.publish("queue_reordered", {"changes": [e.model_dump() for e in moved]})
    done = sorted((p for p in store.packets.values() if p.status in ("approved", "rejected")),
                  key=lambda p: -(p.decided_at or 0))[:20]
    live = [{"session": s.id[:8], "state": s.state, "elapsed_s": s.elapsed_s(), **routes_caller.live_view(s)}
            for s in routes_caller.SESSIONS.values() if not (s.state == "QUEUED" or s.state.startswith("HANDOFF"))]
    return {
        "handoffs": [_item(p, i, r, now) for i, (p, r) in enumerate(store.handoffs())],
        "review": [_item(p, i, r, now) for i, (p, r) in enumerate(store.review(now))],
        "done": [_item(p, i, p.status, now) for i, p in enumerate(done)],
        "audit": [e.model_dump() for e in store.audit[-50:]][::-1],
        "live": live,
    }


@router.get("/api/operator/packet/{pid}")
async def get_packet(pid: str) -> dict:
    _packet(pid)
    p = store.open(pid)  # starts the approval clock
    return P.to_json(p, with_transcript=p.handoff_reason is not None)


@router.post("/api/operator/packet/{pid}/claim")
async def claim(pid: str) -> dict:
    p = _packet(pid)
    try:
        store.claim(pid)
    except TransitionError as e:
        raise HTTPException(409, str(e)) from e
    s = routes_caller.SESSIONS.get(p.session_id)
    if s is not None:  # the caller's screen shows that an officer has the details
        routes_caller.SESSIONS[s.id], _ = next_state(s, Event(type="OPERATOR_TAKEOVER"))
    return _changed(p)


@router.post("/api/operator/packet/{pid}/edit")
async def edit(pid: str, body: EditIn) -> dict:
    p = _packet(pid)
    try:
        store.edit(pid, body.field, body.value, body.txn_index)
    except TransitionError as e:
        raise HTTPException(409, str(e)) from e
    except EditError as e:
        raise HTTPException(422, str(e)) from e
    return _changed(p)


@router.post("/api/operator/packet/{pid}/approve")
async def approve(pid: str) -> dict:
    p = _packet(pid)
    try:
        store.approve(pid)
    except TransitionError as e:
        raise HTTPException(409, str(e)) from e
    return _changed(p)


@router.post("/api/operator/packet/{pid}/reject")
async def reject(pid: str, body: RejectIn) -> dict:
    p = _packet(pid)
    try:
        store.reject(pid, body.reason)
    except TransitionError as e:
        raise HTTPException(409, str(e)) from e
    return _changed(p)


@router.get("/api/events")
async def events() -> StreamingResponse:
    return StreamingResponse(bus.stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

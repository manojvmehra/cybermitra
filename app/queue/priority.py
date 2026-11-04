"""Fair queue ordering. The amount is NEVER a sort key.

Handoffs: wellbeing first, then FIFO.
Review:   1. items waiting longer than QUEUE_MAX_WAIT_S, FIFO among them;
          2. then by *confirmed* last debit time, freshest first (most freezable);
          3. then items with no confirmed time, in arrival order.
An unconfirmed time is "unknown", never "fresh".
"""

from __future__ import annotations

from datetime import datetime

from app.dialog.models import Packet


def review_order(packets: list[Packet], now: float, max_wait_s: float) -> list[tuple[Packet, str]]:
    overdue = sorted((p for p in packets if now - p.created_at > max_wait_s), key=lambda p: (p.created_at, p.id))
    rest = [p for p in packets if now - p.created_at <= max_wait_s]
    timed = sorted((p for p in rest if p.last_debit_time() is not None),
                   key=lambda p: (-(p.last_debit_time() or 0.0), p.created_at, p.id))
    untimed = sorted((p for p in rest if p.last_debit_time() is None), key=lambda p: (p.created_at, p.id))
    out = [(p, f"overdue: waiting > {int(max_wait_s)} s (FIFO)") for p in overdue]
    for p in timed:
        t = datetime.fromtimestamp(p.last_debit_time() or 0).strftime("%d-%m %H:%M")
        out.append((p, f"confirmed last debit {t} (fresher first)"))
    out += [(p, "no confirmed debit time: arrival order") for p in untimed]
    return out


def handoff_order(packets: list[Packet]) -> list[tuple[Packet, str]]:
    def key(p: Packet) -> tuple[int, float, str]:
        return (0 if p.handoff_reason == "wellbeing" else 1, p.created_at, p.id)

    return [(p, "wellbeing first" if p.handoff_reason == "wellbeing" else "arrival order")
            for p in sorted(packets, key=key)]

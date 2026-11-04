"""Queue fairness: the amount never decides order; only caller-confirmed fields and waiting time do."""

import random
from datetime import datetime, timedelta

import pytest

from app.dialog.models import FieldState, Packet
from app.queue import priority
from app.queue.store import QueueStore, TransitionError

NOW = datetime(2026, 11, 3, 18, 0).timestamp()
MAX_WAIT = 300


def pkt(pid: str, *, arrived_s_ago: float, debit: str | None = None, debit_status: str = "confirmed",
        amount: int = 1000, status: str = "ready_for_review", reason: str | None = None) -> Packet:
    t = {"amount": FieldState(name="amount", value=amount, status="confirmed", source="voice"),
         "datetime": FieldState(name="datetime", value=debit, status=debit_status if debit else "empty",
                                source="voice"),
         "utr": FieldState(name="utr")}
    return Packet(id=pid, session_id=pid, lang="ta", status=status, handoff_reason=reason,  # type: ignore[arg-type]
                  txns=[t], created_at=NOW - arrived_s_ago)


def ago(minutes: int) -> str:
    return (datetime.fromtimestamp(NOW) - timedelta(minutes=minutes)).strftime("%d-%m-%Y %H:%M")


def ids(order) -> list[str]:
    return [p.id for p, _ in order]


def test_fresher_confirmed_debit_first():
    ps = [pkt("A", arrived_s_ago=100, debit=ago(120)), pkt("B", arrived_s_ago=50, debit=ago(10)),
          pkt("C", arrived_s_ago=80, debit=ago(60))]
    assert ids(priority.review_order(ps, NOW, MAX_WAIT)) == ["B", "C", "A"]


def test_overdue_jumps_to_top_fifo_among_overdue():
    ps = [pkt("fresh", arrived_s_ago=10, debit=ago(1)), pkt("old2", arrived_s_ago=400, debit=ago(300)),
          pkt("old1", arrived_s_ago=900)]
    order = priority.review_order(ps, NOW, MAX_WAIT)
    assert ids(order) == ["old1", "old2", "fresh"]
    assert order[0][1].startswith("overdue")


def test_unconfirmed_time_sorts_as_unknown_not_fresh():
    ps = [pkt("claims_fresh", arrived_s_ago=20, debit=ago(1), debit_status="unconfirmed"),
          pkt("confirmed_old", arrived_s_ago=100, debit=ago(240)),
          pkt("no_time", arrived_s_ago=50)]
    order = priority.review_order(ps, NOW, MAX_WAIT)
    assert ids(order) == ["confirmed_old", "no_time", "claims_fresh"]  # unknowns in arrival order
    assert "arrival order" in order[2][1]


@pytest.mark.parametrize("seed", range(25))
def test_amount_never_changes_order(seed):
    rng = random.Random(seed)
    base = [pkt(f"P{i}", arrived_s_ago=rng.randint(0, 900),
                debit=ago(rng.randint(1, 600)) if rng.random() < 0.7 else None,
                debit_status=rng.choice(["confirmed", "confirmed", "unconfirmed"]))
            for i in range(12)]
    expected = ids(priority.review_order(base, NOW, MAX_WAIT))
    for _ in range(5):
        for p in base:
            p.txns[0]["amount"].value = rng.choice([1, 500, 49_999, 10_00_000, 9_99_99_999])
        rng.shuffle(base)
        assert ids(priority.review_order(base, NOW, MAX_WAIT)) == expected


def test_order_does_not_read_amount_at_all(monkeypatch):
    calls = []
    monkeypatch.setattr(Packet, "total_amount", lambda self: calls.append(self.id) or 0)
    priority.review_order([pkt("A", arrived_s_ago=1, debit=ago(5)), pkt("B", arrived_s_ago=2)], NOW, MAX_WAIT)
    assert calls == []


def test_handoffs_wellbeing_first_then_fifo():
    ps = [pkt("h1", arrived_s_ago=300, status="needs_human", reason="caller_request"),
          pkt("w", arrived_s_ago=10, status="needs_human", reason="wellbeing"),
          pkt("h2", arrived_s_ago=200, status="claimed", reason="silence")]
    assert ids(priority.handoff_order(ps)) == ["w", "h1", "h2"]


# ---------------------------------------------------------------- store: audit + transitions
def test_every_reorder_is_audited(monkeypatch):
    import app.queue.store as S

    monkeypatch.setattr(S.time, "time", lambda: NOW)
    st = QueueStore()
    st.add(pkt("A", arrived_s_ago=50, debit=ago(100)))
    st.add(pkt("B", arrived_s_ago=40, debit=ago(5)))  # fresher: goes above A
    moves = [(e.packet_id, e.from_pos, e.to_pos) for e in st.audit if e.event == "reorder"]
    assert ("A", None, 0) in moves and ("B", None, 0) in moves and ("A", 0, 1) in moves
    assert all(e.reason for e in st.audit)
    # nothing changes -> nothing audited
    n = len(st.audit)
    assert st.reorder(NOW) == [] and len(st.audit) == n
    # time passes: A becomes overdue and jumps up, with the reason recorded
    moved = st.reorder(NOW + 400)
    assert any(e.packet_id == "A" and e.to_pos == 0 and "overdue" in e.reason for e in moved)


def test_audit_never_contains_values():
    st = QueueStore()
    p = pkt("A", arrived_s_ago=1, amount=123456)
    st.add(p)
    st.edit("A", "victim_mobile", "9876543210")
    st.edit("A", "amount", "777777", txn_index=0)
    assert not any("9876543210" in e.reason or "777777" in e.reason or "123456" in e.reason for e in st.audit)


def test_status_transitions():
    st = QueueStore()
    st.add(pkt("R", arrived_s_ago=1))
    st.add(pkt("H", arrived_s_ago=1, status="needs_human", reason="silence"))
    with pytest.raises(TransitionError):
        st.approve("H")  # a handoff must be claimed first
    with pytest.raises(TransitionError):
        st.claim("R")
    st.claim("H")
    st.approve("H")
    st.open("R")
    st.reject("R", "duplicate")
    with pytest.raises(TransitionError):
        st.approve("R")
    assert st.get("H").approval_latency_s is not None and st.get("R").reject_reason == "duplicate"


def test_edit_sets_operator_source_and_reorders():
    st = QueueStore()
    st.add(pkt("A", arrived_s_ago=10))
    st.add(pkt("B", arrived_s_ago=5, debit=ago(30)))
    st.reorder(NOW)
    assert ids(st.review(NOW)) == ["B", "A"]
    st.edit("A", "datetime", ago(2), txn_index=0)
    f = st.get("A").txns[0]["datetime"]
    assert f.source == "operator" and f.status == "confirmed"
    moved = st.reorder(NOW)
    assert ids(st.review(NOW)) == ["A", "B"] and moved


def test_sweep_drops_expired_packets():
    st = QueueStore()
    st.add(pkt("old", arrived_s_ago=90000))
    st.add(pkt("new", arrived_s_ago=10))
    st.sweep(NOW)
    assert st.get("old") is None and st.get("new") is not None

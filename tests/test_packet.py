"""Complaint Packet (operator) and Victim Summary (caller) rendering."""

from datetime import datetime, timedelta

from app.dialog import packet as P
from app.dialog.models import FieldState, Session, Txn


def f(name: str, value, status: str = "confirmed", source: str = "voice", **kw) -> FieldState:
    return FieldState(name=name, value=value, status=status, source=source, **kw)  # type: ignore[arg-type]


def session() -> Session:
    s = Session(lang="ta")
    t1, t2 = Txn(), Txn()
    t1.fields = {"amount": f("amount", 40000), "datetime": f("datetime", "02-11-2026 15:05", precision="minute"),
                 "utr": f("utr", "430619827418", source="sms")}
    t2.fields = {"amount": f("amount", 10000), "datetime": f("datetime", "02-11-2026 15:09", precision="minute"),
                 "utr": f("utr", None, status="unconfirmed")}
    s.txns = [t1, t2]
    s.fields["fraud_type"] = f("fraud_type", "OTP_BANK_CALL")
    s.fields["victim_bank"] = f("victim_bank", "SBI")
    s.fields["victim_account_last4"] = f("victim_account_last4", "1234", source="sms")
    s.fields["payment_mode"] = f("payment_mode", "UPI")
    s.fields["called_bank"] = f("called_bank", "no")
    s.fields["suspect_phone"] = f("suspect_phone", "9876543218", corrections=1)
    s.fields["district"] = f("district", "Madurai")
    s.created_at = datetime(2026, 11, 2, 15, 20).timestamp()
    s.ended_at = s.created_at + 161
    s.transcripts = ["SBI la irundhu call, 40,000 rupees pochu, number 98765 43218", "aal venum"]
    return s


def test_packet_text_matches_cfcfrms_order():
    text = P.render_text(P.build(session(), "ready_for_review", packet_id="CM-DRAFT-7F3A"))
    lines = text.splitlines()
    assert lines[0].startswith("DRAFT — CM-DRAFT-7F3A — not filed.") and "not affiliated" in lines[0]
    order = ["Status", "Fraud type", "Victim bank", "Called bank?", "Txn 1", "Txn 2", "Total", "Suspect phone",
             "Suspect UPI", "District", "Victim        :", "Handled by AI"]
    pos = [next(i for i, ln in enumerate(lines) if ln.startswith(k)) for k in order]
    assert pos == sorted(pos)
    assert "SBI  (a/c last 4: 1234)" in text and "Payment mode: UPI" in text
    assert "Txn 1         : ₹40,000 [voice ✓] | 02-11-2026 ~15:05 [voice ✓] | UTR 4306 1982 7418 [sms]" in text
    assert "UTR ⚠ verify" in text
    assert "Total         : ₹50,000 (2 transactions)" in text
    assert "98765 43218 [voice ✓ corrected 1×]" in text
    assert "Handled by AI in 2 min 41 s" in text and "last debit ~13 min before call end" in text


def test_handoff_packet_labels_reason_and_carries_masked_transcript():
    p = P.build(session(), "needs_human", "caller_request")
    text = P.render_text(p)
    assert "needs_human (caller asked for a person)" in text and "simulated transfer" in text
    joined = " ".join(p.transcript_masked)
    assert "98765 43218" not in joined and "40,000" not in joined and "aal venum" in joined


def test_ready_packet_has_no_transcript():
    assert P.build(session(), "ready_for_review").transcript_masked == []


def test_packet_id_format():
    pid = P.new_packet_id()
    assert pid.startswith("CM-DRAFT-") and len(pid) == 13


def test_json_flags_verify_fields():
    j = P.to_json(P.build(session(), "ready_for_review"))
    assert j["txns"][1]["utr"]["verify"] is True and j["txns"][0]["utr"]["verify"] is False
    assert j["total"] == 50000 and j["draft"] is True


def test_pending_value_shows_verify():
    s = session()
    s.fields["suspect_phone"].status = "pending"
    assert "98765 43218 ⚠ verify" in P.render_text(P.build(s, "needs_human", "silence"))


def test_empty_txns_dropped():
    s = session()
    s.txns.append(Txn())
    assert len(P.build(s, "ready_for_review").txns) == 2


def test_datetime_display_by_precision():
    assert P.display_datetime(f("datetime", "02-11-2026 18:00", precision="part_of_day")) == "02-11-2026 evening (~18:00)"
    assert P.display_datetime(f("datetime", "02-11-2026 12:00", precision="day")) == "02-11-2026 (time not known)"
    assert P.display_datetime(f("datetime", "02-11-2026 15:05", source="sms", precision="minute")) == "02-11-2026 15:05"
    assert P.display_datetime(f("datetime", "02-11-2026 15:00", precision="hour")) == "02-11-2026 ~15:00"


def test_last_debit_uses_confirmed_times_only():
    s = session()
    s.txns[1].fields["datetime"].status = "unconfirmed"
    p = P.build(s, "ready_for_review")
    assert p.last_debit_time() == datetime(2026, 11, 2, 15, 5).timestamp()


def test_victim_summary_and_draft_tags(monkeypatch):
    s = session()
    v = P.victim_summary(s, "CM-DRAFT-7F3A")
    assert v["n_txns"] == 2 and v["total_display"] == "₹50,000"
    assert "CM-DRAFT-7F3A" in v["text"] and "NCRP" in v["text"]
    assert len(v["next_steps"]) == 5 and all(x["draft"] for x in v["next_steps"])  # no source recorded yet
    from app.dialog import prompts
    monkeypatch.setattr(prompts, "NEXT_STEPS_SOURCED", {"NS_CALL_1930"})
    v = P.victim_summary(s, "CM-DRAFT-7F3A")
    assert [x["draft"] for x in v["next_steps"]] == [True, False, True, True, True]


def test_no_forbidden_pii_reaches_packet():
    from app.dialog.models import Event
    from app.dialog.state_machine import next_state

    s, _ = next_state(Session(lang="en"), Event(type="START"))
    s, _ = next_state(s, Event(type="AUDIO_TURN", text="en OTP 482913, 50,000 rupees pochu"))
    s, _ = next_state(s, Event(type="AUDIO_TURN", text="aadhaar number 1234 5678 9012"))
    s, _ = next_state(s, Event(type="HUMAN"))
    p = P.build(s, "needs_human", "caller_request")
    blob = P.render_text(p) + str(P.to_json(p, with_transcript=True))
    assert "482913" not in blob and "9012" not in blob


def test_relative_time_in_footer():
    s = session()
    end = datetime.fromtimestamp(s.ended_at or 0)
    s.txns[0].fields["datetime"].value = (end - timedelta(hours=2, minutes=5)).strftime("%d-%m-%Y %H:%M")
    s.txns[1].fields["datetime"].status = "unconfirmed"
    assert "last debit ~2 h 5 min before call end" in P.render_text(P.build(s, "ready_for_review"))

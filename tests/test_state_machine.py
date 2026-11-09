"""Scripted calls against the pure FSM (no network)."""

from app.dialog import packet as P
from app.dialog.models import Event, Session
from app.dialog.state_machine import next_state


class Dialog:
    """story_check="no" answers the one-shot story check with 2, so a test walks the per-field read-backs;
    None leaves the check for the test to answer."""

    def __init__(self, lang: str = "en", story_check: str | None = "no") -> None:
        self.s = Session(lang=lang)  # type: ignore[arg-type]
        self.acts: list = []
        self.story_check = story_check
        self.send(Event(type="START"))

    def send(self, ev: Event) -> "Dialog":
        self.s, self.acts = next_state(self.s, ev)
        if self.story_check and self.s.state == "STORY_CHECK" and ev.type != "BACK":
            first = self.acts
            self.s, self.acts = next_state(self.s, Event(type="BUTTON", field="story", answer=self.story_check))
            self.acts = first + self.acts
        return self

    def say(self, text: str, literal: str | None = None) -> "Dialog":
        return self.send(Event(type="AUDIO_TURN", text=text, literal=literal))

    def button(self, answer: str) -> "Dialog":
        rb = self.s.readback
        assert rb is not None, (self.s.state, self.spoken)
        return self.send(Event(type="BUTTON", field=rb.field, txn_index=rb.txn_index, chunk_index=rb.index,
                               answer=answer))  # type: ignore[arg-type]

    def yesno(self, field: str, answer: str) -> "Dialog":
        return self.send(Event(type="BUTTON", field=field, answer=answer))  # type: ignore[arg-type]

    def sms(self, text: str) -> "Dialog":
        return self.send(Event(type="SMS_PASTED", text=text))

    @property
    def spoken(self) -> str:
        return " | ".join(a.text or "" for a in self.acts if a.type == "SpeakPrompt")

    def at(self, state: str, field: str | None = None, txn: int | None = None) -> None:
        assert self.s.state == state, (self.s.state, self.s.current_field, self.spoken)
        if field:
            assert self.s.current_field == field, (self.s.current_field, self.spoken)
        if txn is not None:
            assert self.s.current_txn == txn, (self.s.current_txn, self.spoken)

    def yes(self, n: int) -> None:
        for _ in range(n):
            self.button("yes")

    def until(self, field: str, txn: int | None = None) -> None:
        """Answer with ✓ / "don't know" until the FSM asks about `field`."""
        for _ in range(60):
            if self.s.current_field == field and (txn is None or self.s.current_txn == txn):
                return
            if self.s.state == "READBACK":
                self.button("yes")
            elif self.s.state == "ASK_MORE_TXN":
                self.yesno("more_txn", "no")
            elif self.s.state == "GAP_FILL" and self.s.current_field == "called_bank":
                self.yesno("called_bank", "no")
            else:
                self.say("theriyala")
        raise AssertionError(f"never asked for {field}")

    def finish(self) -> None:
        """Answer the rest with "don't know" until the call ends with its summary."""
        for _ in range(60):
            if self.s.state == "QUEUED":
                return
            if self.s.state == "READBACK":
                self.button("yes")
            elif self.s.state == "ASK_MORE_TXN":
                self.yesno("more_txn", "no")
            elif self.s.current_field == "called_bank":
                self.yesno("called_bank", "no")
            else:
                self.say("theriyala")
        raise AssertionError("did not reach QUEUED")

    def packet(self, status: str = "ready_for_review") -> str:
        return P.render_text(P.build(self.s, status, self.s.handoff_reason))


NARRATIVE = ("SBI la irundhu call vandhuchu, KYC update nu OTP kettanga, 50,000 rupees pochu. "
             "andha number 98765 43218")
LITERAL = ("எஸ்பிஐ la irundhu call vandhuchu, KYC update nu OTP kettanga, aimbadhaayiram rupees pochu. "
           "andha number ஒன்பது எட்டு ஏழு ஆறு ஐந்து நான்கு மூன்று இரண்டு ஒன்று எட்டு")
SMS_1 = ("Rs.40,000.00 debited from A/c XX1234 on 02-11-26 15:05 to VPA fraud.pay@ybl UPI Ref No 430619827418. -SBI")
SMS_2 = ("Rs.10,000.00 debited from A/c XX1234 on 02-11-26 15:09 to VPA fraud.pay@ybl UPI Ref No 430619827555. -SBI")
SMS_3 = ("Rs.5,000.00 debited from A/c XX1234 on 02-11-26 15:20 to VPA fraud.pay@ybl UPI Ref No 430619820001. -SBI")


def test_start_speaks_opening():
    d = Dialog()
    d.at("NARRATIVE")
    for must in ("1930", "AI", "Press 1 for yes", "2 for no", "press star", "hash", "in one go", "what happened",
                 "when", "how much", "UPI", "which bank"):
        assert must in d.spoken
    assert "OTP" not in d.spoken and "freeze" not in d.spoken  # the caller dialled 1930: no disclaimers


def test_happy_path_one_transaction():
    d = Dialog(story_check=None)
    d.say(NARRATIVE, LITERAL)
    # one check for everything the story gave
    d.at("STORY_CHECK")
    assert "fifty thousand rupees" in d.spoken and "from your SBI account" in d.spoken
    assert d.s.txns[0].fields["amount"].value == 50000
    assert d.s.txns[0].fields["amount"].confidence == "high"
    assert d.s.fields["fraud_type"].value == "OTP_BANK_CALL"
    assert "Transaction" not in d.spoken  # one transaction: no "Transaction 1:" prefix
    d.yesno("story", "yes")
    assert d.s.txns[0].fields["amount"].status == "confirmed"
    assert d.s.fields["victim_bank"].status == "confirmed"
    # then only what the story left out
    d.at("GAP_FILL", "datetime", 0)
    d.say("yesterday evening 3 mani")
    d.at("READBACK", "datetime")
    d.say("yes")
    d.at("ASK_MORE_TXN")  # the tests run with MAX_TXNS=10
    d.say("illa, adhu mattum thaan")
    d.at("GAP_FILL", "payment_mode")
    d.say("GPay la anuppinen")
    d.say("yes")
    d.at("GAP_FILL", "suspect_upi")
    d.say("theriyala")
    d.at("GAP_FILL", "suspect_bank")
    d.say("theriyala")
    d.at("GAP_FILL", "called_bank")
    d.say("illa")
    d.at("GAP_FILL", "district")
    d.say("Madurai")
    d.say("yes")
    d.at("GAP_FILL", "victim_name")
    d.say("my name is Test Kumar")
    d.say("yes")
    # typed numbers come last
    d.at("GAP_FILL", "utr")
    d.send(Event(type="NUMPAD", field="utr", txn_index=0, digits="4306 1982 7418"))
    d.at("READBACK", "suspect_phone")  # heard in the story, so read back rather than typed
    assert d.s.fields["suspect_phone"].value == "9876543218"
    d.say("yes")
    d.say("yes")
    d.at("GAP_FILL", "victim_mobile")
    d.send(Event(type="NUMPAD", field="victim_mobile", digits="9123456780"))
    # no review question: a spoken summary, the SMS, goodbye
    d.at("QUEUED")
    assert "I have noted fifty thousand rupees, yesterday, 3 PM, by UPI, from your SBI account" in d.spoken
    assert "SMS" in d.spoken and "Goodbye" in d.spoken
    assert "Call your bank" not in d.spoken  # the next steps go in the SMS, not the call
    push = [a for a in d.acts if a.type == "PushPacket"]
    assert push and push[0].data["status"] == "ready_for_review"
    text = d.packet()
    for must in ("₹50,000", "[voice ✓]", "98765 43218", "Madurai", "4306 1982 7418", "UPI", "Called bank?  : No",
                 "Total         : ₹50,000 (1 transaction)", "Handled by AI"):
        assert must in text, (must, text)


def test_story_check_no_reads_each_value_back():
    d = Dialog(story_check=None)
    d.say("nethu 3 mani SBI account la irundhu 40,000 rupees pochu, GPay la")
    d.at("STORY_CHECK")
    assert "forty thousand rupees" in d.spoken and "by UPI" in d.spoken and "from your SBI account" in d.spoken
    d.yesno("story", "no")
    assert "one by one" in d.spoken
    d.at("READBACK", "amount", 0)
    assert all(f.status != "confirmed" for f in (d.s.txns[0].fields["amount"], d.s.fields["victim_bank"]))


def test_story_check_by_voice_and_unclear_answer():
    d = Dialog(story_check=None)
    d.say("40,000 rupees pochu")
    d.at("STORY_CHECK")
    d.say("mm")
    d.at("STORY_CHECK")
    assert "Press 1 if it is right" in d.spoken
    d.say("aama")
    assert d.s.txns[0].fields["amount"].status == "confirmed"
    d.at("GAP_FILL", "datetime", 0)


def test_story_with_nothing_to_check_goes_to_the_questions():
    d = Dialog(story_check=None)
    d.say("enakku romba bayama irukku")  # no amount, time, mode or bank
    d.at("GAP_FILL", "amount", 0)


def test_three_transactions_two_voice_one_sms():
    d = Dialog()
    d.say("moonu thadava panam pochu. first 40,000 rupees, apram 10,000 rupees")
    assert d.s.expected_txn_count == 3
    assert [t.fields["amount"].value for t in d.s.txns] == [40000, 10000]
    d.at("READBACK", "amount", 0)
    assert "Transaction 1:" in d.spoken
    d.button("yes")
    d.at("GAP_FILL", "datetime", 0)
    d.say("nethu 3 mani")
    d.button("yes")
    d.at("READBACK", "amount", 1)
    assert "Transaction 2:" in d.spoken
    d.button("yes")
    d.say("nethu 3:10")
    d.button("yes")
    d.at("ASK_MORE_TXN")
    assert "3 times" in d.spoken  # caller said three; two captured so far
    d.say("aama, innoru irukku")
    d.at("GAP_FILL", "amount", 2)
    d.sms(SMS_3)  # the third debit, pasted
    t3 = d.s.txns[2].fields
    assert t3["amount"].value == 5000 and t3["amount"].source == "sms" and t3["utr"].status == "confirmed"
    d.at("ASK_MORE_TXN")
    d.yesno("more_txn", "no")
    d.until("utr", 0)  # typed numbers are asked last, for each transaction still missing one
    d.say("four three zero six one nine eight two seven four one eight")
    d.yes(3)
    d.at("GAP_FILL", "utr", 1)
    d.send(Event(type="SKIP", field="utr", txn_index=1))
    d.finish()
    assert "I have noted" in d.spoken
    text = d.packet()
    assert "Txn 3" in text and "₹55,000 (3 transactions)" in text and "[sms]" in text


def test_sms_paste_two_debits_makes_two_transactions():
    d = Dialog()
    d.sms(SMS_1 + "\n\n" + SMS_2)
    d.at("NARRATIVE")
    assert len(d.s.txns) == 2
    assert all(t.fields[k].source == "sms" for t in d.s.txns for k in ("amount", "utr", "datetime"))
    assert d.s.fields["victim_bank"].value == "SBI" and d.s.fields["victim_account_last4"].value == "1234"
    assert d.s.fields["payment_mode"].value == "UPI"
    d.say("call vandhuchu, 40,000 rupees pochu, andha number 98765 43218")
    assert len(d.s.txns) == 2  # the spoken 40,000 is the pasted debit, not a third one
    d.at("ASK_MORE_TXN")  # SMS fields are not re-read
    d.yesno("more_txn", "no")
    d.until("suspect_phone")  # numbers come last; this one was heard in the story, so it is read back
    d.at("READBACK", "suspect_phone")


def test_sms_with_no_new_debit_keeps_question():
    d = Dialog()
    d.sms(SMS_1)
    d.say("panam pochu")
    d.at("ASK_MORE_TXN")
    d.sms(SMS_1)  # same UTR again: nothing new
    assert len(d.s.txns) == 1
    d.at("ASK_MORE_TXN")


def test_voice_correction_last_digit():
    d = Dialog()
    d.say("andha number 98765 43210 la irundhu call vandhuchu")
    d.until("suspect_phone")
    d.at("READBACK", "suspect_phone")
    d.say("yes")
    assert d.s.readback.index == 1
    d.say("illa, kadaisi number ettu")
    d.at("READBACK", "suspect_phone")
    assert d.s.readback.chunks[1] == "43218"
    assert d.s.fields["suspect_phone"].value == "9876543218"
    d.say("aama")
    assert d.s.fields["suspect_phone"].status == "confirmed"
    assert d.s.fields["suspect_phone"].corrections == 1
    assert "corrected 1×" in d.packet()


def test_no_then_spoken_chunk():
    d = Dialog()
    d.say("andha number 98765 43210")
    d.until("suspect_phone")
    d.say("illa")
    assert d.s.readback.awaiting == "correct" and d.s.show_numpad
    d.say("nine eight seven six four")
    assert d.s.readback.chunks[0] == "98764"


def test_two_failed_repairs_unconfirmed():
    d = Dialog()
    d.say("50,000 rupees pochu")
    d.at("READBACK", "amount")
    d.button("no")
    d.say("fifty thousand")
    d.button("no")
    d.say("fifty thousand")
    d.button("no")  # third "no": out of repairs
    assert d.s.txns[0].fields["amount"].status == "unconfirmed"
    d.at("GAP_FILL", "datetime", 0)
    assert "⚠ verify" in d.packet()


def test_gapfill_failures_unconfirmed():
    d = Dialog()
    d.say("en panam pochu")
    d.at("GAP_FILL", "amount")
    d.say("blah blah")
    d.say("blah blah")
    d.at("GAP_FILL", "amount")
    d.say("blah blah")
    assert d.s.txns[0].fields["amount"].status == "unconfirmed"


def test_two_fields_given_up_hands_off():
    d = Dialog()
    d.say("en panam pochu")
    for _ in range(3):
        d.say("blah blah")
    d.at("GAP_FILL", "datetime")
    for _ in range(3):
        d.say("blah blah")
    d.at("HANDOFF_HUMAN")
    assert d.s.handoff_reason == "repairs_exhausted"


def test_wrong_length_utr_prompt():
    d = Dialog()
    d.say("ennoda panam pochu")
    d.until("utr")
    d.say("four three zero six one nine eight two seven four one")
    assert "11" in d.spoken and d.s.state == "GAP_FILL"


def test_silence_twice_handoff_with_partial_packet():
    d = Dialog()
    d.say("50,000 rupees pochu")
    d.button("yes")
    d.say("")
    d.at("GAP_FILL", "datetime")
    d.say("")
    d.at("HANDOFF_HUMAN")
    assert d.s.handoff_reason == "silence"
    assert "stay on the line" in d.spoken and "simulated" in d.spoken
    push = [a for a in d.acts if a.type == "PushPacket"]
    assert push[0].data == {"status": "needs_human", "reason": "silence"}
    p = P.build(d.s, "needs_human", "silence")
    assert p.txns[0]["amount"].value == 50000 and p.txns[0]["amount"].status == "confirmed"
    assert p.transcript_masked and "50,000" not in " ".join(p.transcript_masked)


def test_timeout_counts_as_silence():
    d = Dialog()
    d.send(Event(type="TIMEOUT"))
    d.send(Event(type="TIMEOUT"))
    d.at("HANDOFF_HUMAN")


def test_aal_venum_mid_call_warm_handoff_keeps_confirmed_fields():
    d = Dialog()
    d.say(NARRATIVE, LITERAL)
    d.say("aama")
    d.say("yesterday evening 3 mani")
    d.say("yes")
    d.at("ASK_MORE_TXN")
    d.say("enakku aal venum")
    d.at("HANDOFF_HUMAN")
    assert d.s.handoff_reason == "caller_request"
    p = P.build(d.s, "needs_human", "caller_request")
    t = p.txns[0]
    assert t["amount"].status == "confirmed" and t["datetime"].status == "confirmed"
    assert p.fields["suspect_phone"].value == "9876543218"  # captured, awaiting confirmation: shown as verify
    text = P.render_text(p)
    assert "needs_human (caller asked for a person)" in text and "⚠ verify" in text
    assert any("aal venum" in x for x in p.transcript_masked)


def test_human_button_forces_handoff():
    d = Dialog()
    d.send(Event(type="HUMAN"))
    d.at("HANDOFF_HUMAN")


def test_otp_spoken_is_dropped():
    d = Dialog()
    d.say("en OTP 482913")
    d.at("NARRATIVE")
    assert "Never share" in d.spoken
    assert all("482913" not in t for t in d.s.transcripts)
    assert all("482913" not in str(f.value) for f in d.s.fields.values())


def test_otp_during_readback_reasks_chunk():
    d = Dialog()
    d.say("50,000 rupees pochu")
    d.say("my pin is 4321")
    d.at("READBACK", "amount")
    assert "Never share" in d.spoken and "Amount" in d.spoken


def test_sextortion_handoff_nonfin():
    d = Dialog()
    d.say("avan en morphed photo podren nu blackmail panran")
    d.at("HANDOFF_NONFIN")
    assert d.s.handoff_reason == "non_financial"
    assert all(f.value is None for k, f in d.s.fields.items())
    assert "cybercrime.gov.in" in d.spoken


def test_self_harm_handoff_wellbeing():
    d = Dialog()
    d.say("ellam pochu, enakku saaganum pola irukku")
    d.at("HANDOFF_WELLBEING")
    assert d.s.handoff_reason == "wellbeing"
    assert "14416" in d.spoken


def test_terminal_state_is_sticky():
    d = Dialog()
    d.say("aal venum")
    d.say("50,000 rupees pochu")
    d.at("HANDOFF_HUMAN")
    assert not d.acts


def test_operator_takeover_marks_claimed():
    d = Dialog()
    d.say("aal venum")
    d.send(Event(type="OPERATOR_TAKEOVER"))
    assert d.s.operator_claimed


def test_duplicate_utr_detected():
    d = Dialog()
    d.say("rendu thadava pochu, 40,000 rupees and 10,000 rupees")
    d.button("yes")
    d.say("nethu 3 mani")
    d.button("yes")
    d.at("READBACK", "amount", 1)
    d.button("yes")
    d.say("nethu 3 mani")
    d.button("yes")
    d.yesno("more_txn", "no")
    d.until("utr", 0)
    d.say("four three zero six one nine eight two seven four one eight")
    d.yes(3)
    d.at("GAP_FILL", "utr", 1)
    d.say("four three zero six one nine eight two seven four one eight")
    d.at("DUP_CHECK")
    assert "same transaction" in d.spoken
    d.yesno("dup_utr", "yes")
    assert len(d.s.txns) == 1
    assert d.s.state != "DUP_CHECK" and d.s.current_field != "utr"


def test_duplicate_utr_no_means_reask():
    d = Dialog()
    d.sms(SMS_1)
    d.say("innoru 10,000 rupees pochu")
    d.at("READBACK", "amount", 1)  # the story's second amount opens transaction 2
    d.button("yes")
    d.say("nethu 3 mani")
    d.button("yes")
    d.send(Event(type="NUMPAD", field="utr", txn_index=1, digits="430619827418"))
    d.at("DUP_CHECK")
    d.say("illa")
    d.at("GAP_FILL", "utr", 1)


def test_numpad_is_authoritative():
    d = Dialog()
    d.say("andha number 98765 43210")
    d.send(Event(type="NUMPAD", field="suspect_phone", digits="9876543218"))
    f = d.s.fields["suspect_phone"]
    assert f.status == "confirmed" and f.source == "numpad" and f.value == "9876543218"
    assert "[typed ✓]" in d.packet()


def test_numpad_chunk_correction():
    d = Dialog()
    d.say("andha number 98765 43210")
    d.until("suspect_phone")
    d.button("yes")
    d.button("no")
    d.send(Event(type="NUMPAD", field="suspect_phone", digits="43218"))
    assert d.s.fields["suspect_phone"].value == "9876543218"


def test_numpad_invalid():
    d = Dialog()
    d.say("andha number 98765 43210")
    d.send(Event(type="NUMPAD", field="suspect_phone", digits="12345"))
    assert d.s.fields["suspect_phone"].source != "numpad"
    assert any(a.type == "ShowNumpad" for a in d.acts)


def test_skip_field():
    d = Dialog()
    d.say("ennoda panam pochu")
    d.at("GAP_FILL", "amount")
    d.send(Event(type="SKIP", field="amount", txn_index=0))
    assert d.s.txns[0].fields["amount"].status == "skipped"
    d.at("GAP_FILL", "datetime")


def test_skip_during_story_moves_to_questions():
    d = Dialog()
    d.send(Event(type="SKIP", field="amount"))
    d.at("GAP_FILL", "amount", 0)
    assert "How much" in d.spoken


def test_stale_button_ignored():
    d = Dialog()
    d.say("50,000 rupees pochu")
    before = d.s.model_copy(deep=True)
    d.send(Event(type="BUTTON", field="utr", chunk_index=0, answer="yes"))
    assert d.s.txns == before.txns


def test_low_confidence_offers_numpad():
    d = Dialog()
    d.say("andha number 98765 43210", "andha number ஒன்பது எட்டு ஏழு ஆறு ஐந்து நான்கு மூன்று இரண்டு ஒன்று எட்டு")
    d.until("suspect_phone")
    assert d.s.fields["suspect_phone"].confidence == "low"
    assert d.s.fields["suspect_phone"].value == "9876543218"
    assert d.s.show_numpad


def test_repeat_rereads_chunk():
    d = Dialog()
    d.say("50,000 rupees pochu")
    d.say("thirumba")
    d.at("READBACK", "amount")
    assert "fifty thousand" in d.spoken


def test_three_unclear_answers_hand_off():
    d = Dialog()
    d.say("50,000 rupees pochu")
    d.say("hmm")
    d.say("hmm")
    d.say("hmm")
    d.at("HANDOFF_HUMAN")
    assert d.s.handoff_reason == "not_understood"


def test_max_turns_hands_off(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MAX_TURNS_PER_CALL", "3")
    get_settings.cache_clear()
    d = Dialog()
    d.say("50,000 rupees pochu")
    d.say("thirumba")
    d.say("thirumba")
    d.say("thirumba")
    d.at("HANDOFF_HUMAN")
    assert d.s.handoff_reason == "max_turns"


def test_high_amount_extra_confirmation():
    d = Dialog()
    d.say("15 lakh rupees pochu")
    d.say("yes")
    assert "ten lakh" in d.spoken


def test_call_ends_with_a_summary_and_no_review_question():
    d = Dialog()
    d.say("ennoda panam pochu")
    d.finish()
    d.at("QUEUED")
    assert "your complaint" in d.spoken and "SMS" in d.spoken  # nothing confirmed to sum up
    assert any(a.type == "ShowSummary" for a in d.acts)


def test_called_bank_by_button():
    d = Dialog()
    d.say("ennoda panam pochu")
    d.until("called_bank")
    d.yesno("called_bank", "yes")
    assert d.s.fields["called_bank"].value == "yes" and d.s.fields["called_bank"].status == "confirmed"


def test_tamil_dialog_prompts():
    d = Dialog("ta")
    d.say("ஐம்பதாயிரம் ரூபாய் போச்சு")
    assert "சரியா?" in d.spoken
    assert "ஐம்பது ஆயிரம் ரூபாய்" in d.spoken


def test_old_date_warning():
    d = Dialog()
    d.sms("Rs 100 debited on 01-01-2026 10:00 Ref 111122223333")
    assert d.s.txns[0].fields["datetime"].status == "confirmed"
    d2 = Dialog()
    d2.say("ennoda panam pochu")
    d2.send(Event(type="SKIP", field="amount", txn_index=0))
    d2.say("10 days ago morning 10 mani")
    d2.say("yes")
    assert "7 days" in d2.spoken


def test_day_only_story_time_is_asked_not_guessed():
    d = Dialog()
    d.say("nethu 50,000 rupees pochu")
    d.button("yes")
    d.at("GAP_FILL", "datetime")


def test_part_of_day_readback_phrase():
    d = Dialog()
    d.say("ennoda panam pochu")
    d.send(Event(type="SKIP", field="amount", txn_index=0))
    d.say("nethu saayangaalam")
    d.at("READBACK", "datetime")
    assert "yesterday, evening" in d.spoken
    assert d.s.txns[0].fields["datetime"].precision == "part_of_day"


def test_max_txns(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MAX_TXNS", "1")
    get_settings.cache_clear()
    d = Dialog()
    d.sms(SMS_1)
    d.say("panam pochu")
    assert "officer will add" not in d.spoken  # nobody mentioned a second debit
    assert d.s.state != "ASK_MORE_TXN" and d.s.phase == "CASE" and len(d.s.txns) == 1


def test_default_is_a_single_transaction():
    from app.config import Settings

    assert Settings.model_fields["MAX_TXNS"].default == 1


def test_single_txn_never_asks_for_another(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MAX_TXNS", "1")
    get_settings.cache_clear()
    d = Dialog()
    d.say("ennoda panam pochu")
    d.send(Event(type="SKIP", field="amount", txn_index=0))
    d.send(Event(type="SKIP", field="datetime", txn_index=0))
    d.send(Event(type="SKIP", field="utr", txn_index=0))
    assert d.s.state != "ASK_MORE_TXN" and d.s.phase == "CASE"
    assert "other transaction" not in d.spoken


def test_second_debit_over_the_cap_reaches_the_operator(monkeypatch):
    from app.config import get_settings
    from app.dialog import packet as P

    monkeypatch.setenv("MAX_TXNS", "1")
    get_settings.cache_clear()
    d = Dialog()
    d.sms(SMS_1 + "\n\n" + SMS_2)
    d.say("panam pochu")
    assert len(d.s.txns) == 1 and "officer will add" in d.spoken
    p = P.build(d.s, "needs_human", "caller_request")
    assert p.reported_txn_count == 2
    assert "caller mentioned 2 transactions, 1 captured" in P.render_text(p)


def test_real_prisma_smoke_output():
    """Exact Prisma v2.5 output for scripts/make_smoke_clip.py (synthetic numbers), captured 2026-11-02."""
    from app.gnani.stt import SttResult
    from app.nlp.extractor import extract_rules, find_bank

    r = SttResult(
        text="நேற்று எஸ்பி பேங்க்லிருந்து பேசுகிறோன்னு ஒரு கால் வந்துச்சு ஓடிபி கேட்டாங்க ₹50,000 போச்சு அந்த 9876543218",
        literal="நேற்று எஸ்பி பேங்க்லிருந்து பேசுகிறோன்னு ஒரு கால் வந்துச்சு ஓடிபி கேட்டாங்க ஐம்பதாயிரம் ரூபாய் போச்சு "
                "அந்த நம்பர் ஒன்பது எட்டு ஏழு ஆறு ஐந்து நான்கு மூன்று இரண்டு ஒன்று எட்டு",
        model="prisma-v2.5", detected_language=None, truncated=False, latency_ms=0, cached=False)
    c = extract_rules(r)
    assert c["amount"].value == 50000 and c["amount"].confidence == "high"
    assert "amount.1" not in c
    assert c["suspect_phone"].value == "9876543218" and c["suspect_phone"].confidence == "high"
    assert c["bank"].value == "SBI"
    assert c["fraud_type"].value == "OTP_BANK_CALL"
    assert find_bank("எஸ் பை பேங்க்லிருந்து") == ("SBI", "எஸ் பை")
    assert find_bank("எஸ்பி ஆபீஸ்ல இருந்து") is None  # police SP, not a bank


# ---------------------------------------------------------------- back
def _at_utr() -> Dialog:
    d = Dialog()
    d.say(NARRATIVE, LITERAL)
    d.until("utr")
    return d


def test_back_is_not_offered_before_the_first_answer():
    d = Dialog()
    assert d.s.history == []
    d.send(Event(type="BACK"))
    d.at("NARRATIVE")
    assert d.acts == []


def test_back_from_the_first_question_returns_to_the_story():
    d = Dialog()
    d.say("theriyala")
    assert d.s.state != "NARRATIVE"
    d.send(Event(type="BACK"))
    d.at("NARRATIVE")
    assert "Tell me what happened" in d.spoken and not d.s.txns


def test_back_clears_a_typed_answer_so_it_can_be_entered_again():
    d = _at_utr()
    d.send(Event(type="NUMPAD", field="utr", digits="111122223333"))
    assert d.s.txns[0].fields["utr"].status == "confirmed" and d.s.current_field != "utr"
    d.send(Event(type="BACK"))
    d.at("GAP_FILL", "utr")
    f = d.s.txns[0].fields["utr"]
    assert f.value is None and f.status == "empty" and "UTR" in d.spoken
    d.send(Event(type="NUMPAD", field="utr", digits="444455556666"))
    assert d.s.txns[0].fields["utr"].value == "444455556666"


def test_back_steps_through_readback_chunks_and_never_confirms():
    d = _at_utr()
    d.say("4306 1982 7418")
    d.at("READBACK", "utr")
    d.button("yes")
    assert d.s.readback.index == 1
    d.send(Event(type="BACK"))
    assert d.s.readback.index == 0 and d.s.txns[0].fields["utr"].status == "pending"
    assert any(a.type == "ShowReadback" for a in d.acts)


def test_back_keeps_the_call_limits_and_transcript():
    d = _at_utr()
    d.say("4306 1982 7418")
    turns, said = d.s.turns, list(d.s.transcripts)
    d.send(Event(type="BACK"))
    assert d.s.turns == turns and d.s.transcripts == said


def test_a_reasked_question_is_not_a_step():
    d = _at_utr()
    n = len(d.s.history)
    d.say("idhu enna solla")
    assert len(d.s.history) == n


def test_back_can_undo_a_chain_of_answers():
    d = Dialog()
    d.say(NARRATIVE, LITERAL)
    d.until("victim_mobile")
    while d.s.history:
        d.send(Event(type="BACK"))
    d.at("NARRATIVE")
    assert not d.s.txns and d.s.fields["suspect_phone"].value is None


def test_back_does_nothing_after_the_packet_is_pushed():
    d = Dialog()
    d.say(NARRATIVE, LITERAL)
    d.finish()
    d.at("QUEUED")
    d.send(Event(type="BACK"))
    d.at("QUEUED")


def test_back_history_is_bounded_and_has_no_nested_history():
    d = Dialog()
    d.say(NARRATIVE, LITERAL)
    d.finish()
    assert 0 < len(d.s.history) <= 30
    assert all("history" not in h and "transcripts" not in h for h in d.s.history)


# ---------------------------------------------------------------- whole UTR at once
def test_utr_typed_whole_in_any_spacing():
    for typed in ("430619827418", "4306 1982 7418", "4306-1982-7418"):
        d = _at_utr()
        d.send(Event(type="NUMPAD", field="utr", digits=typed))
        assert d.s.txns[0].fields["utr"].value == "430619827418", typed


def test_utr_spoken_whole_in_any_spacing():
    for said in ("430619827418", "4306 1982 7418"):
        d = _at_utr()
        d.say(said)
        d.at("READBACK", "utr")
        assert d.s.txns[0].fields["utr"].value == "430619827418", said


def test_whole_utr_typed_during_a_correction_replaces_the_number():
    d = _at_utr()
    d.say("430619827418")
    d.button("no")
    d.send(Event(type="NUMPAD", field="utr", digits="1111 2222 3333"))
    assert d.s.txns[0].fields["utr"].value == "111122223333"


def test_whole_utr_said_during_a_correction_replaces_the_number():
    d = _at_utr()
    d.say("430619827418")
    d.button("no")
    d.say("1111 2222 3333")
    assert d.s.txns[0].fields["utr"].value == "111122223333"
    d.at("READBACK", "utr")
    assert d.s.txns[0].fields["utr"].status == "pending"


# ---------------------------------------------------------------- the 1930 line: numbers are typed
def test_utr_is_asked_to_be_typed_after_star():
    d = Dialog()
    d.say("50,000 rupees pochu")
    d.button("yes")
    d.until("utr", 0)
    d.at("GAP_FILL", "utr")
    assert "press star, type it, then press hash" in d.spoken and "press 2" in d.spoken
    assert not any(a.type == "ShowNumpad" for a in d.acts), "typing starts only when the caller presses star"
    d.send(Event(type="NUMPAD", field="utr", txn_index=0, digits="430619827418"))
    f = d.s.txns[0].fields["utr"]
    assert f.value == "430619827418" and f.status == "confirmed" and f.source == "numpad"


def test_mobile_numbers_are_asked_to_be_typed():
    d = Dialog()
    d.say("50,000 rupees pochu")
    d.until("suspect_phone")
    assert "fraudster called from: press star, type it" in d.spoken
    d.yesno("suspect_phone", "no")  # 2: "I don't know it"
    assert d.s.fields["suspect_phone"].status == "skipped"
    d.at("GAP_FILL", "victim_mobile")
    assert "Your mobile number: press star" in d.spoken


def test_typed_number_with_the_wrong_length_says_how_many_digits():
    d = Dialog()
    d.say("50,000 rupees pochu")
    d.until("suspect_phone")
    d.send(Event(type="NUMPAD", field="suspect_phone", digits="98765"))
    assert "5 digits" in d.spoken and "type it again" in d.spoken
    d.at("GAP_FILL", "suspect_phone")


def test_an_amount_the_ai_cannot_understand_is_typed():
    d = Dialog()
    d.say("theriyala")  # no amount in the story
    d.at("GAP_FILL", "amount")
    d.say("romba panam")  # "a lot of money": no number in it
    assert "Press star, type the amount" in d.spoken
    d.send(Event(type="NUMPAD", field="amount", txn_index=0, digits="25000"))
    f = d.s.txns[0].fields["amount"]
    assert f.value == 25000 and f.status == "confirmed" and f.source == "numpad"


def test_mobile_starting_with_0_to_5_says_why():
    d = Dialog()
    d.say("50,000 rupees pochu")
    d.until("victim_mobile")
    d.send(Event(type="NUMPAD", field="victim_mobile", digits="1234567890"))
    assert "starts with 6, 7, 8 or 9" in d.spoken
    d.at("GAP_FILL", "victim_mobile")
    d.send(Event(type="NUMPAD", field="victim_mobile", digits="9123456780"))
    assert d.s.fields["victim_mobile"].status == "confirmed"


def test_noise_on_a_typed_number_question_explains_the_keys_and_costs_nothing():
    d = Dialog()
    d.say("50,000 rupees pochu")
    d.until("victim_mobile")
    for _ in range(4):  # no number in it: never "didn't catch", never a give-up or handoff
        d.say("hmm okay")
        d.at("GAP_FILL", "victim_mobile")
        assert "Press star, type it" in d.spoken and "didn't catch" not in d.spoken
    assert not d.s.repair_attempts.get("victim_mobile")


def test_a_wrong_typed_number_again_and_again_moves_on():
    d = Dialog()
    d.say("50,000 rupees pochu")
    d.until("victim_mobile")
    for _ in range(3):
        d.send(Event(type="NUMPAD", field="victim_mobile", digits="12345"))
    assert d.s.fields["victim_mobile"].status == "unconfirmed"  # an officer checks it; the call is not stuck
    assert d.s.current_field != "victim_mobile"

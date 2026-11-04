"""Understanding: how people actually answer, and what Prisma actually writes."""

from datetime import datetime

import pytest

from app.dialog.readback import render_datetime
from app.dialog.state_machine import clean_name
from app.nlp.extractor import find_datetime, find_upi
from app.nlp.yesno import classify
from tests.test_state_machine import Dialog

NOW = datetime(2026, 11, 3, 18, 0)


# ---------------------------------------------------------------- yes / no as Prisma writes it
@pytest.mark.parametrize("text,intent", [
    ("எஸ்", "YES"), ("யெஸ் கரெக்ட்டு", "YES"), ("ஆமாங்க", "YES"), ("ரைட்", "YES"),
    ("நோ", "NO"), ("ராங்", "NO"), ("வேணாம்", "NO"), ("தப்பா இருக்கு", "NO"), ("இல்லீங்க", "NO"),
    ("டோன்ட் நோ", "DONT_KNOW"), ("தெரியலங்க", "DONT_KNOW"), ("மறந்துட்டேன்", "DONT_KNOW"), ("ஸ்கிப்", "DONT_KNOW"),
    ("ரிப்பீட்", "REPEAT"), ("புரியல", "REPEAT"), ("once more please", "REPEAT"),
    ("ஆபீசர் கிட்ட பேசணும்", "HUMAN"),
])
def test_tamil_script_answers(text, intent):
    assert classify(text).intent == intent


# ---------------------------------------------------------------- read-back behaviour
def to_phone(d: Dialog) -> None:
    d.until("suspect_phone")


def test_repeating_the_chunk_confirms_it():
    d = Dialog()
    d.say("andha number 98765 43218")
    to_phone(d)
    d.say("98765")
    assert d.s.readback.index == 1  # moved on, no correction counted
    assert d.s.fields["suspect_phone"].corrections == 0 and not d.s.repair_attempts


def test_resaying_whole_number_confirms_field():
    d = Dialog()
    d.say("andha number 98765 43218")
    to_phone(d)
    d.say("ஒன்பது எட்டு ஏழு ஆறு ஐந்து நான்கு மூன்று இரண்டு ஒன்று எட்டு")
    assert d.s.fields["suspect_phone"].status == "confirmed"


def test_resaying_different_whole_number_replaces_and_resumes():
    d = Dialog()
    d.say("andha number 98765 43210")
    to_phone(d)
    d.say("yes")  # first chunk 98765 confirmed
    d.say("illa, 98765 43218")
    f = d.s.fields["suspect_phone"]
    assert f.value == "9876543218" and f.corrections == 1
    assert d.s.readback.index == 1 and d.s.readback.chunks[1] == "43218"  # resumes at the changed chunk
    d.say("aama")
    assert f.status == "confirmed" or d.s.fields["suspect_phone"].status == "confirmed"


def test_amount_repeated_back_confirms():
    d = Dialog("ta")
    d.say("ஐம்பதாயிரம் ரூபாய் போச்சு")
    d.say("ஐம்பதாயிரம்")
    assert d.s.txns[0].fields["amount"].status == "confirmed"


def test_unclear_answer_reasks_without_spending_a_repair():
    d = Dialog()
    d.say("50,000 rupees pochu")
    d.say("ம்")
    assert d.s.state == "READBACK" and d.s.readback.awaiting == "confirm"
    assert not d.s.repair_attempts and "Say 'yes'" in d.spoken
    d.say("ம்")  # still unclear: now it is treated as "no"
    assert d.s.readback.awaiting == "correct" and d.s.repair_attempts["amount#0"] == 1


def test_unclear_never_confirms():
    d = Dialog()
    d.say("50,000 rupees pochu")
    for _ in range(4):
        d.say("ம்")
    assert d.s.txns[0].fields["amount"].status != "confirmed"


def test_no_to_optional_upi_question_skips():
    d = Dialog()
    d.say("ennoda panam pochu")
    d.until("suspect_upi")
    d.say("இல்ல")
    assert d.s.fields["suspect_upi"].status == "skipped" and d.s.current_field == "suspect_bank"


# ---------------------------------------------------------------- names and typed text
@pytest.mark.parametrize("raw,name", [
    ("என் பெயர் ரமேஷ்", "ரமேஷ்"), ("ரமேஷ்ங்க", "ரமேஷ்"), ("my name is Test Kumar sir", "Test Kumar"),
    ("naan Priya", "Priya"), ("Karthik nu peru", "Karthik"), ("என்னோட பேரு கவிதா", "கவிதா"),
])
def test_clean_name(raw, name):
    assert clean_name(raw) == name


@pytest.mark.parametrize("field,typed,value", [
    ("victim_bank", "state bank of india", "SBI"), ("victim_bank", "Some Co-op Bank", "Some Co-op Bank"),
    ("payment_mode", "google pay", "UPI"), ("called_bank", "aama", "yes"),
    ("district", "madurai", "Madurai"), ("district", "Hosur", "Hosur"),
    ("suspect_upi", "Fraud.Pay@YBL", "fraud.pay@ybl"), ("victim_name", "my name is Asha", "Asha"),
])
def test_typed_text_fields(field, typed, value):
    from app.dialog.models import Event

    d = Dialog()
    d.say("ennoda panam pochu")
    d.send(Event(type="NUMPAD", field=field, digits=typed))
    f = d.s.fields[field]
    assert f.value == value and f.source == "numpad" and f.status == "confirmed"


def test_typed_bad_upi_rejected():
    from app.dialog.models import Event

    d = Dialog()
    d.send(Event(type="NUMPAD", field="suspect_upi", digits="not a upi"))
    assert d.s.fields["suspect_upi"].value is None


# ---------------------------------------------------------------- time understanding
@pytest.mark.parametrize("text,expected", [
    ("நேத்து சாயங்காலம் மூணு மணிக்கு", "02-11-2026 15:00"),
    ("முந்தாநேத்து காலையில 10 மணி", "01-11-2026 10:00"),   # not "yesterday" (contains நேத்து)
    ("2 மணி நேரம் முன்னாடி", "03-11-2026 16:00"),           # a duration, not 2 o'clock
    ("அரை மணி நேரம் முன்னாடி", "03-11-2026 17:30"),
    ("10 நிமிஷம் முன்னாடி", "03-11-2026 17:50"),
    ("இப்போ தான்", "03-11-2026 17:55"),                      # "just now" ≈ 5 minutes ago
    ("இன்னைக்கு மூணரை மணிக்கு", "03-11-2026 15:30"),
    ("நவம்பர் 1 இரவு 9 மணி", "01-11-2026 21:00"),
    ("yesterday 3:30 pm", "02-11-2026 15:30"),
    ("3 மணிக்கு", "03-11-2026 15:00"),                       # bare 3 o'clock = afternoon
    ("today 11 am", "03-11-2026 11:00"),
    ("ராத்திரி 2 மணி", "03-11-2026 02:00"),
    ("nethu night 10 mani", "02-11-2026 22:00"),
    ("5 naal munnadi", "29-10-2026 12:00"),
    ("2 November", "02-11-2026 12:00"),
    ("December 25", "25-12-2025 12:00"),                     # would be future this year -> last year
])
def test_find_datetime(text, expected):
    assert find_datetime(text, NOW).strftime("%d-%m-%Y %H:%M") == expected


def test_find_datetime_none():
    assert find_datetime("something else entirely", NOW) is None


def test_bare_early_hour_stays_morning_if_afternoon_is_future():
    morning = datetime(2026, 11, 3, 9, 0)
    assert find_datetime("இன்னைக்கு 6 மணிக்கு", morning).hour == 6


def test_render_datetime():
    assert render_datetime("02-11-2026 15:30", "en") == "2 November, 3:30 PM"
    assert render_datetime("02-11-2026 15:00", "ta") == "நவம்பர் இரண்டு, மதியம் மூன்று மணி"
    assert render_datetime("01-11-2026 21:05", "ta").endswith("இரவு ஒன்பது மணி ஐந்து நிமிடம்")
    assert render_datetime("2 Nov evening", "en") == "2 Nov evening"


def test_find_upi_tamil_script():
    assert find_upi("ramesh dot k அட் தி ரேட் ybl") == "ramesh.k@ybl"
    assert find_upi("abc at the rate of okaxis") == "abc@okaxis"


def test_typed_datetime_keeps_precision():
    from app.dialog.models import Event

    d = Dialog()
    d.say("ennoda panam pochu")
    d.send(Event(type="NUMPAD", field="datetime", txn_index=0, digits="yesterday evening"))
    f = d.s.txns[0].fields["datetime"]
    assert f.status == "confirmed" and f.precision == "part_of_day" and f.value.endswith("18:00")

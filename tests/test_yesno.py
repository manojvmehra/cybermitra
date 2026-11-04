import pytest

from app.nlp.yesno import YesNo, apply_correction, classify


@pytest.mark.parametrize("text", ["ஆமா", "ஆமாம்", "சரி", "சரிதான்", "ok", "okay", "yes", "correct", "aama", "sari",
                                  "seri", "haan", "சரிங்க", "aama sir", "Yes, correct."])
def test_yes(text):
    assert classify(text).intent == "YES"


@pytest.mark.parametrize("text", ["இல்ல", "இல்லை", "தப்பு", "வேண்டாம்", "illa", "thappu", "no", "wrong", "இல்லைங்க",
                                  "illainga", "no no"])
def test_no(text):
    assert classify(text).intent == "NO"


@pytest.mark.parametrize("text", ["தெரியல", "theriyala", "don't know", "theriyadhu", "skip"])
def test_dont_know(text):
    assert classify(text).intent == "DONT_KNOW"


@pytest.mark.parametrize("text", ["திரும்ப சொல்லுங்க", "thirumba", "again", "repeat please", "enna"])
def test_repeat(text):
    assert classify(text).intent == "REPEAT"


@pytest.mark.parametrize("text", ["ஆள் வேணும்", "aal venum", "I want an officer", "human please"])
def test_human(text):
    assert classify(text).intent == "HUMAN"


def test_any_no_wins():
    assert classify("sari illa").intent == "NO"
    assert classify("yes no").intent == "NO"


def test_unknown():
    assert classify("").intent == "UNKNOWN"
    assert classify("hmm blah").intent == "UNKNOWN"


def test_correction_last():
    yn = classify("illa, kadaisi number ettu")
    assert yn.intent == "CORRECTION" and yn.digits == "8" and yn.position == "last"
    assert apply_correction("43210", yn) == "43218"


def test_correction_first_tamil():
    yn = classify("இல்ல, முதல் நம்பர் ஏழு")
    assert yn.intent == "CORRECTION" and yn.position == "first"
    assert apply_correction("98765", yn) == "78765"


def test_correction_full_chunk():
    yn = classify("no, four three two one eight")
    assert apply_correction("43210", yn) == "43218"


def test_correction_unresolvable():
    yn = classify("illa ettu")  # one digit, no position
    assert yn.intent == "CORRECTION"
    assert apply_correction("43210", yn) is None
    assert apply_correction("43210", YesNo("NO")) is None


def test_bare_digits_is_correction():
    yn = classify("four three two one eight")
    assert yn.intent == "CORRECTION" and yn.digits == "43218"

import pytest

from app.dialog.readback import render_amount_en, render_amount_ta, render_digits_en, render_digits_ta
from app.nlp import lexicon_ta as L
from app.nlp.numbers import find_number_spans, format_inr, normalise_text, parse_amount, parse_digit_string

# ---------------------------------------------------------------- every lexicon row
UNIT_ROWS = [(v, s) for tbl in (L.UNITS_TA, L.UNITS_ROMAN, L.UNITS_EN) for v, ss in tbl.items() for s in ss]
TEEN_TENS_ROWS = [(v, s) for tbl in (L.TEENS_TA, L.TEENS_ROMAN, L.TEENS_EN, L.TENS_TA, L.TENS_ROMAN, L.TENS_EN)
                  for v, ss in tbl.items() for s in ss]
HUND_ROWS = [(v, s) for tbl in (L.HUNDREDS_TA, L.HUNDREDS_ROMAN) for v, ss in tbl.items() for s in ss]
MULT_ROWS = [(v, s) for tbl in (L.MULTS_TA, L.MULTS_ROMAN, L.MULTS_EN) for v, ss in tbl.items() for s in ss
             if s != "k"]


@pytest.mark.parametrize("value,surface", UNIT_ROWS)
def test_unit_rows_as_digit(value, surface):
    assert parse_digit_string(surface).value == str(value)


@pytest.mark.parametrize("value,surface", TEEN_TENS_ROWS)
def test_teen_tens_rows(value, surface):
    assert parse_amount(surface).value == value


@pytest.mark.parametrize("value,surface", HUND_ROWS)
def test_hundred_rows(value, surface):
    assert parse_amount(surface).value == value


@pytest.mark.parametrize("value,surface", MULT_ROWS)
def test_multiplier_rows(value, surface):
    # "<one> <multiplier>" and a bare multiplier both mean 1×multiplier
    assert parse_amount(surface).value == value


@pytest.mark.parametrize("surface,value", [
    ("அரை லட்சம்", 50_000), ("கால் லட்சம்", 25_000), ("முக்கால் லட்சம்", 75_000),
    ("arai latcham", 50_000), ("kaal latcham", 25_000), ("mukkaal latcham", 75_000),
    ("half lakh", 50_000), ("ஒன்றரை லட்சம்", 150_000), ("ரெண்டரை லட்சம்", 250_000),
    ("onnara latcham", 150_000), ("rendara latcham", 250_000), ("ஒன்னரை லட்சம்", 150_000),
])
def test_fractions(surface, value):
    assert parse_amount(surface).value == value


# ---------------------------------------------------------------- 30+ compound amounts
COMPOUNDS = [
    ("ஐம்பதாயிரம்", 50_000), ("ஐம்பது ஆயிரம்", 50_000), ("aimbadhaayiram", 50_000), ("fifty thousand", 50_000),
    ("இருபத்தைந்து", 25), ("இருபத்தி ஐந்து", 25), ("இருபத்தஞ்சு", 25), ("நூற்றி ஐம்பது", 150), ("நூற்றைம்பது", 150),
    ("இரண்டு லட்சத்து இருபத்தைந்தாயிரம்", 225_000), ("rendu latchathi irubathanju aayiram", 225_000),
    ("two lakh twenty five thousand", 225_000), ("2,25,000", 225_000), ("₹2,25,000", 225_000),
    ("ஒரு லட்சத்து ஐம்பதாயிரம்", 150_000), ("1,50,000", 150_000), ("1.5 lakh", 150_000),
    ("one and a half lakh", 150_000), ("one lakh fifty thousand", 150_000),
    ("நாற்பத்தொன்பதாயிரத்து தொள்ளாயிரத்து தொண்ணூற்றொன்பது", 49_999), ("49,999", 49_999),
    ("forty nine thousand nine hundred ninety nine", 49_999),
    ("ஒரு லட்சத்து ஐநூறு", 100_500), ("1,00,500", 100_500), ("one lakh five hundred", 100_500),
    ("பன்னிரண்டு லட்சத்து முப்பத்து நான்காயிரத்து ஐநூற்று அறுபத்தேழு", 1_234_567), ("12,34,567", 1_234_567),
    ("twelve lakh thirty four thousand five hundred sixty seven", 1_234_567),
    ("50k", 50_000), ("₹50,000", 50_000), ("50000", 50_000), ("Rs. 50,000", 50_000), ("5,20,000", 520_000),
    ("ஐந்தாயிரம்", 5_000), ("anjaayiram", 5_000), ("பத்தாயிரம்", 10_000), ("pathaayiram", 10_000),
    ("ரெண்டு கோடி", 20_000_000), ("ஒரு கோடியே ஐம்பது லட்சம்", 15_000_000), ("ten crore", 100_000_000),
    ("twelve hundred", 1_200), ("five hundred rupees", 500), ("ஐநூறு ரூபாய்", 500), ("anju aayiram rubaa", 5_000),
    ("ஆயிரத்து ஐநூறு", 1_500), ("aayirathu ainooru", 1_500), ("ஐம்பதாயிரமும்", 50_000),
    ("ஆயிரத்துக்கு", 1_000), ("₹499.50", 499), ("எழுபத்தைந்தாயிரம்", 75_000), ("thonnootthi onbadhu", 99),
    ("onnara lakh", 150_000), ("2 lakh", 200_000), ("2 lakh 50 thousand", 250_000),
]


@pytest.mark.parametrize("surface,value", COMPOUNDS)
def test_compound_amounts(surface, value):
    r = parse_amount(surface)
    assert r.value == value, (surface, r)


def test_amount_in_sentence():
    assert parse_amount("ஐம்பதாயிரம் ரூபாய் போச்சு சார்").value == 50_000
    assert parse_amount("en account la irundhu aimbadhaayiram rubaa cut aachu").value == 50_000
    assert parse_amount("they took 50,000 rupees from my SBI account").value == 50_000


def test_methods():
    assert parse_amount("50000").method == "itn_digits"
    assert parse_amount("ஐம்பதாயிரம்").method == "tamil_words"
    assert parse_amount("aimbadhaayiram").method == "roman_words"
    assert parse_amount("fifty thousand").method == "english_words"
    assert parse_amount("anju lakh").method == "mixed"


# ---------------------------------------------------------------- 20 phone digit strings
PHONES = [
    ("9876543210", "9876543210"), ("98765 43210", "9876543210"), ("+91 98765 43210", "919876543210"),
    ("nine eight seven six five four three two one zero", "9876543210"),
    ("ஒன்பது எட்டு ஏழு ஆறு ஐந்து நான்கு மூன்று இரண்டு ஒன்று பூஜ்ஜியம்", "9876543210"),
    ("ombadhu ettu ezhu aaru anju naalu moonu rendu onnu poojyam", "9876543210"),
    ("double nine eight seven six five four three two one", "9987654321"),
    ("nine triple eight seven six five four three two", "9888765432"),
    ("டபுள் ஒன்பது எட்டு ஏழு ஆறு ஐந்து நான்கு மூன்று இரண்டு ஒன்று", "9987654321"),
    ("nine eight seven six five, four three two one eight", "9876543218"),
    ("ஒன்பது eight ஏழு six ஐந்து four மூன்று two ஒன்று zero", "9876543210"),
    ("98765 um 43218", "9876543218"), ("nine eight seven six five uh four three two one eight", "9876543218"),
    ("ninety eight seventy six fifty four thirty two ten", "9876543210"),
    ("தொண்ணூற்றெட்டு எழுபத்தாறு ஐம்பத்திநாலு முப்பத்திரெண்டு பத்து", "9876543210"),
    ("seven zero zero zero zero nine eight seven six five", "7000098765"),
    ("six double zero double zero one one one two two", "6000011122"),
    ("ஆறு டபுள் பூஜ்ஜியம் டபுள் பூஜ்ஜியம் ஒன்று ஒன்று ஒன்று இரண்டு இரண்டு", "6000011122"),
    ("ettu poojyam poojyam poojyam poojyam onnu rendu moonu naalu anju", "8000012345"),
    ("9123456780", "9123456780"), ("onbathu onnu rendu moonu naalu anju aaru ezhu ettu poojyam", "9123456780"),
]


@pytest.mark.parametrize("surface,digits", PHONES)
def test_phone_digit_strings(surface, digits):
    r = parse_digit_string(surface, len(digits))
    assert r.value == digits, (surface, r)


# ---------------------------------------------------------------- 20 UTR strings
UTRS = [
    "430619827418", "512300004567", "600011112222", "123400005678", "998877660011", "100020003000",
    "777788889999", "000011112222", "314159265358", "271828182845",
]


@pytest.mark.parametrize("utr", UTRS)
def test_utr_digits_and_words_en(utr):
    assert parse_digit_string(utr, 12).value == utr
    assert parse_digit_string(render_digits_en(utr), 12).value == utr


@pytest.mark.parametrize("utr", UTRS)
def test_utr_words_ta_chunked(utr):
    spoken = " ".join(render_digits_ta(utr[i:i + 4]) for i in range(0, 12, 4))
    assert parse_digit_string(spoken, 12).value == utr


def test_utr_spaced_itn():
    assert parse_digit_string("UTR 4306 1982 7418", 12).value == "430619827418"


# ---------------------------------------------------------------- adversarial
@pytest.mark.parametrize("surface", [
    "rendu moonu naal aachu",         # "two-three days" — not an amount
    "oru call vandhuchu",            # "a call came" — article, not an amount
    "ஒரு கால் வந்துச்சு",              # call/quarter — no multiplier
    "ara mani neram aachu",          # "half an hour"
    "yaaru nu theriyala",            # contains no number word
    "naan bank ku ponen",
    "aana avan solla",
    "someone called me",
    "ok ok sari",
    "",
])
def test_adversarial_no_amount(surface):
    assert parse_amount(surface).value is None


def test_range_is_not_guessed():
    r = parse_amount("rendu moonu latcham irukkum")
    assert r.value is None and "range" in r.warnings


def test_multiple_amounts_without_currency_is_ambiguous():
    r = parse_amount("ஐம்பதாயிரம் இல்ல அறுபதாயிரம்")
    assert r.value is None and "multiple_amounts" in r.warnings


def test_currency_disambiguates():
    assert parse_amount("first 5 days later 20,000 rupees pochu").value == 20_000


def test_phone_not_amount():
    assert parse_amount("98765 43210").value is None


def test_filler_gap_splits_spans():
    spans = find_number_spans("nine eight seven umm uh six five")
    assert len(spans) == 2


def test_filler_single_gap_keeps_span():
    spans = find_number_spans("nine eight seven uh six five")
    assert len(spans) == 1 and spans[0].digits == "98765"


def test_repeated_words_digits():
    assert parse_digit_string("ettu ettu ettu", 3).value == "888"


def test_length_mismatch_warning():
    r = parse_digit_string("nine eight seven", 10)
    assert r.value == "987" and "length_mismatch" in r.warnings


def test_merged_spans_only_when_exact():
    r = parse_digit_string("nine eight seven six five then four three two one zero", 10)
    assert r.value == "9876543210" and "merged_spans" in r.warnings


def test_no_digits():
    assert parse_digit_string("theriyala sir").value is None


def test_tamil_digits_normalised():
    assert normalise_text("௫௦௦௦௦") == "50000"
    assert parse_amount("௫௦,௦௦௦ ரூபாய்").value == 50_000


# ---------------------------------------------------------------- round trips
@pytest.mark.parametrize("digits", ["9876543210", "0000000000", "1234567890", "4306", "98765", "000", "7"])
def test_roundtrip_digits_ta(digits):
    assert parse_digit_string(render_digits_ta(digits)).value == digits


@pytest.mark.parametrize("digits", ["9876543210", "0000000000", "1234567890", "4306"])
def test_roundtrip_digits_en(digits):
    assert parse_digit_string(render_digits_en(digits)).value == digits


@pytest.mark.parametrize("n", [1, 9, 10, 11, 19, 20, 25, 99, 100, 101, 150, 500, 999, 1000, 1001, 1500, 9999, 10_000,
                               12_500, 25_000, 49_999, 50_000, 99_999, 100_000, 100_500, 150_000, 225_000,
                               999_999, 1_000_000, 1_234_567, 9_999_999, 10_000_000, 15_000_000, 100_000_000])
def test_roundtrip_amount_words(n):
    assert parse_amount(render_amount_ta(n)).value == n
    assert parse_amount(render_amount_en(n)).value == n


def test_format_inr():
    assert format_inr(50000) == "₹50,000"
    assert format_inr(1234567) == "₹12,34,567"
    assert format_inr(999) == "₹999"
    assert format_inr(100000000) == "₹10,00,00,000"

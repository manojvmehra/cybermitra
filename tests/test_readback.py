from app.dialog import readback as R
from app.nlp.numbers import parse_amount


def test_phone_chunks():
    assert R.chunk("suspect_phone", "9876543218") == ["98765", "43218"]


def test_utr_chunks():
    assert R.chunk("utr", "430619827418") == ["4306", "1982", "7418"]


def test_upi_chunks():
    assert R.chunk("suspect_upi", "fraudpay1@ybl") == ["frau", "dpay", "1", "@ybl"]


def test_amount_single_chunk():
    assert R.chunk("amount", 50000) == ["50000"]


def test_digit_words_comma_separated():
    assert R.render_digits_ta("4306") == "நான்கு, மூன்று, பூஜ்ஜியம், ஆறு"
    assert R.render_digits_en("998") == "nine, nine, eight"  # never "double nine"


def test_amount_words():
    assert R.render_amount_ta(50000) == "ஐம்பது ஆயிரம் ரூபாய்"
    assert R.render_amount_en(150000) == "one lakh fifty thousand rupees"
    assert parse_amount(R.render_amount_ta(225000)).value == 225000


def test_step_text_ta():
    st = R.step("suspect_phone", ["98765", "43218"], 1, "ta")
    assert st.chunk_digits == "43218" and st.total_chunks == 2
    assert "சரியா?" in st.text and "இரண்டாம் பகுதி" in st.text and "43218" not in st.text


def test_step_text_en():
    st = R.step("amount", ["50000"], 0, "en")
    assert st.text == "Amount: fifty thousand rupees. Is that right?"


def test_upi_words():
    assert R.chunk_words("suspect_upi", "@ybl", "en") == "at, y, b, l"
    assert R.chunk_words("suspect_upi", "ab12", "en") == "a, b, one, two"


def test_text_field_passthrough():
    assert R.chunk_words("bank", "SBI", "en") == "SBI"

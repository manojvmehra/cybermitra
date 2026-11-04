"""Regressions from real Prisma output (probe 2026-11-02, synthetic TTS clips, fake numbers)."""

from app.dialog.models import Event, Session
from app.dialog.state_machine import next_state
from app.nlp import safety
from app.nlp.numbers import parse_amount, parse_digit_string


def test_english_numbers_in_tamil_script():
    t = "ஃபிஃப்டி தௌசண்ட் ருபீஸ் போச்சு நம்பர் நைன் எயிட் செவன் சிக்ஸ் ஃபைவ் ஃபோர் த்ரீ டூ ஒன் எயிட்"
    assert parse_amount(t).value == 50000
    assert parse_digit_string("நைன் எயிட் செவன் சிக்ஸ் ஃபைவ் ஃபோர் த்ரீ டூ ஒன் எயிட்", 10).value == "9876543218"


def test_prisma_colloquial_twenty_five_thousand():
    assert parse_amount("இருபத்தந்தாயிரம் ரூபாய் கட்டாச்சு").value == 25000


def test_itn_half_conversion():
    # B_v25_transcribe ITN output: "ஒன்றரை லட்சம்" -> "ஒன்றரை 1,00,000"
    assert parse_amount("அக்கவுண்ட்லேருந்து ஒன்றரை 1,00,000 இன்வெஸ்ட் பண்ணு").value == 150000


def test_v3_transliterate_variants():
    assert parse_amount("ambadhaiyiram roobai pacha").value == 50000
    assert parse_amount("rendu lakshath irubathaindhaayiram roobai").value == 225000
    assert parse_amount("ondru laksham invest pannen").value == 100000
    assert parse_amount("naarpathombathayirathu thollayirathu roobai").value == 49900


def test_ninety_nine_spaced_combining():
    assert parse_amount("நாற்பத்தொம்பதாயிரத்து தொள்ளாயிரத்து தொண்ணூற்றி ஒன்பது ரூபா").value == 49999


def test_digital_arrest_threat_is_not_sextortion():
    t = ("சிபிஐலிருந்து வீடியோ கால் பண்ணாங்க பார்சலில் ட்ரக்ஸ் இருக்குன்னு மிரட்டினாங்க இந்தியன் பேங்க்லிருந்து "
         "₹2,25,000 அனுப்பினேன்")
    assert "NONFIN" not in safety.check(t).flags
    s, _ = next_state(Session(lang="ta"), Event(type="START"))
    s, _ = next_state(s, Event(type="AUDIO_TURN", text=t))
    assert s.state != "HANDOFF_NONFIN" and s.txns[0].fields["amount"].value == 225000


def test_pin_story_with_amount_is_not_a_secret():
    t = "பின் போட்டேன் எச்டிஎஃப்சி அக்கவுண்ட்டிலிருந்து ₹25,000 கட்டாச்சு"
    assert "SECRET" not in safety.check(t).flags
    assert "SECRET" not in safety.check("upi pin pottaen, 25000 rubaa pochu").flags
    assert "SECRET" not in safety.check("அதுக்கு பின் 5000 ரூபாய் போச்சு").flags


def test_spoken_secret_still_caught():
    assert "SECRET" in safety.check("en OTP 482913").flags
    assert "SECRET" in safety.check("my atm pin is 4321").flags
    assert "SECRET" in safety.check("ஓடிபி நான்கு எட்டு இரண்டு ஒன்பது ஒன்று மூன்று").flags
    assert "ID" in safety.check("aadhaar number 1234 5678 9012").flags


def test_repeated_digit_loss_is_caught_by_length_check():
    # Prisma dropped a repeated "ஒன்று": 6000011122 -> 9 digits. The app must re-ask, not accept.
    from app.nlp.validators import validate_phone

    d = parse_digit_string("ஆறு பூஜ்ஜியம் பூஜ்ஜியம் பூஜ்ஜியம் பூஜ்ஜியம் ஒன்று ஒன்று இரண்டு இரண்டு", 10).value
    assert d == "600001122" and validate_phone(str(d)).reason == "phone_len_9"

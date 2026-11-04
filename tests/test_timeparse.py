"""Spoken debit times -> estimate + precision, with `now` fixed (Tue 03-11-2026 18:00)."""

from datetime import datetime

import pytest

from app.nlp.timeparse import parse_time

NOW = datetime(2026, 11, 3, 18, 0)


@pytest.mark.parametrize("text,expected,precision", [
    # relative
    ("12 nimisham munnadi", "03-11-2026 17:48", "minute"),
    ("12 minutes munnadi", "03-11-2026 17:48", "minute"),
    ("12 நிமிஷம் முன்னாடி", "03-11-2026 17:48", "minute"),
    ("10 minutes ago", "03-11-2026 17:50", "minute"),
    ("arai mani nerathukku munnadi", "03-11-2026 17:30", "minute"),
    ("அரை மணி நேரம் முன்னாடி", "03-11-2026 17:30", "minute"),
    ("oru mani neram munnadi", "03-11-2026 17:00", "hour"),
    ("rendu mani neram aachu", "03-11-2026 16:00", "hour"),
    ("2 மணி நேரம் முன்னாடி", "03-11-2026 16:00", "hour"),
    ("ஒன்றரை மணி நேரம் முன்னாடி", "03-11-2026 16:30", "minute"),
    ("3 hours ago", "03-11-2026 15:00", "hour"),
    ("ippo thaan", "03-11-2026 17:55", "minute"),
    ("just now", "03-11-2026 17:55", "minute"),
    ("இப்போ தான்", "03-11-2026 17:55", "minute"),
    # day words alone
    ("innaikku", "03-11-2026 12:00", "day"),
    ("nethu", "02-11-2026 12:00", "day"),
    ("நேத்து", "02-11-2026 12:00", "day"),
    ("mundhaanethu", "01-11-2026 12:00", "day"),
    ("முந்தாநேத்து", "01-11-2026 12:00", "day"),
    ("5 naal munnadi", "29-10-2026 12:00", "day"),
    # part of day
    ("innaikku kaalaila", "03-11-2026 09:00", "part_of_day"),
    ("nethu madhiyam", "02-11-2026 13:00", "part_of_day"),
    ("nethu saayangaalam", "02-11-2026 18:00", "part_of_day"),
    ("நேத்து ராத்திரி", "02-11-2026 21:00", "part_of_day"),
    ("mundhaanethu raathiri", "01-11-2026 21:00", "part_of_day"),
    ("raathiri", "02-11-2026 21:00", "part_of_day"),            # latest past night
    ("kaalaila", "03-11-2026 09:00", "part_of_day"),
    # clock
    ("pathu mani", "03-11-2026 10:00", "hour"),
    ("11 mani", "03-11-2026 11:00", "hour"),
    ("3:30", "03-11-2026 15:30", "minute"),
    ("moonarai mani", "03-11-2026 15:30", "minute"),
    ("மூணரை மணிக்கு", "03-11-2026 15:30", "minute"),
    ("3 மணிக்கு", "03-11-2026 15:00", "hour"),
    ("innaikku kaalai pathinonnu mani", "03-11-2026 11:00", "hour"),
    ("nethu saayangaalam 6 mani", "02-11-2026 18:00", "hour"),
    ("nethu night 10 mani", "02-11-2026 22:00", "hour"),
    ("ராத்திரி 2 மணி", "03-11-2026 02:00", "hour"),
    ("yesterday 3:30 pm", "02-11-2026 15:30", "minute"),
    ("today 11 am", "03-11-2026 11:00", "hour"),
    ("nethu 3 mani", "02-11-2026 15:00", "hour"),
    # explicit dates
    ("நவம்பர் 1 இரவு 9 மணி", "01-11-2026 21:00", "hour"),
    ("2 November", "02-11-2026 12:00", "day"),
    ("December 25", "25-12-2025 12:00", "day"),
    # ITN / SMS pass-through
    ("02-11-2026 15:05", "02-11-2026 15:05", "minute"),
    ("02-11-2026", "02-11-2026 00:00", "day"),
    ("02/11/2026 15:05", "02-11-2026 15:05", "minute"),
])
def test_parse_time(text, expected, precision):
    r = parse_time(text, NOW)
    assert r.formatted() == expected, (text, r)
    assert r.precision == precision, (text, r.precision)


@pytest.mark.parametrize("text", ["naalaikku 3 mani", "tomorrow morning", "நாளைக்கு", "05-11-2026 10:00"])
def test_future_is_rejected_with_warning(text):
    r = parse_time(text, NOW)
    assert r.value is None and r.warnings == ["future"]


@pytest.mark.parametrize("text", ["", "something else entirely", "SBI la irundhu call", "50,000 rupees pochu"])
def test_no_time(text):
    assert parse_time(text, NOW).value is None


def test_bare_early_hour_stays_morning_if_afternoon_is_future():
    morning = datetime(2026, 11, 3, 9, 0)
    assert parse_time("இன்னைக்கு 6 மணிக்கு", morning).value.hour == 6


def test_clock_said_before_it_happened_today_is_yesterday():
    early = datetime(2026, 11, 3, 8, 0)
    assert parse_time("pathu mani", early).formatted() == "02-11-2026 22:00"  # latest past 10 o'clock


def test_method_reports_script():
    assert parse_time("நேத்து", NOW).method == "tamil_words"
    assert parse_time("nethu", NOW).method == "roman_words"
    assert parse_time("02-11-2026 15:05", NOW).method == "itn_digits"

from datetime import datetime, timedelta

import pytest

from app.nlp import validators as V


@pytest.mark.parametrize("raw,ok,val", [
    ("9876543210", True, "9876543210"), ("+91 98765 43210", True, "9876543210"), ("919876543210", True, "9876543210"),
    ("09876543210", True, "9876543210"), ("5876543210", False, None), ("987654321", False, None),
    ("98765432101", False, None), ("", False, None),
])
def test_phone(raw, ok, val):
    v = V.validate_phone(raw)
    assert v.ok == ok
    if ok:
        assert v.value == val


def test_phone_reason_len():
    assert V.validate_phone("987654321").reason == "phone_len_9"


@pytest.mark.parametrize("raw,ok,reason", [
    ("430619827418", True, ""), ("4306 1982 7418", True, ""), ("43061982741", False, "utr_len_11"),
    ("4306198274189", False, "utr_len_13"),
])
def test_utr(raw, ok, reason):
    v = V.validate_utr(raw)
    assert v.ok == ok and v.reason == reason


@pytest.mark.parametrize("raw,ok", [("fraud.pay@ybl", True), ("abc-1@okhdfcbank", True), ("a@ybl", False),
                                    ("noat", False), ("x y@ybl", True), ("abc@1bank", False)])
def test_upi(raw, ok):
    assert V.validate_upi(raw).ok == ok


def test_amount():
    assert V.validate_amount(50000).ok
    assert not V.validate_amount(0).ok
    assert not V.validate_amount(None).ok
    assert not V.validate_amount(10_00_00_001).ok
    assert V.validate_amount(10_00_001).extra_confirm
    assert not V.validate_amount(10_00_000).extra_confirm


def test_datetime():
    now = datetime(2026, 11, 2, 18, 0)
    assert V.validate_datetime(now - timedelta(hours=3), now).ok
    assert V.validate_datetime(now + timedelta(days=1), now).reason == "datetime_future"
    assert V.validate_datetime(now - timedelta(days=9), now).warn == "older_than_7_days"
    assert not V.validate_datetime(None, now).ok

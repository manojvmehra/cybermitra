"""Synthetic bank / UPI SMS formats (all numbers fake)."""

import pytest

from app.nlp.sms_parser import parse_sms, sms_datetime

CASES = [
    ("Rs.50,000.00 debited from A/c XX1234 on 01-11-26 15:02 to VPA fraud.pay@ybl UPI Ref No 430619827418. -SBI",
     {"amount": 50000, "utr": "430619827418", "bank": "SBI", "suspect_upi": "fraud.pay@ybl", "datetime": "01-11-2026 15:02",
      "victim_account_last4": "1234"}),
    ("Dear Customer, INR 25,000.00 has been debited from account **5678 to VPA abc123@okhdfcbank on 02-11-26. "
     "UPI Ref 512300004567. Not you? Call 18002586161 -HDFC Bank",
     {"amount": 25000, "utr": "512300004567", "bank": "HDFC", "suspect_upi": "abc123@okhdfcbank"}),
    ("ICICI Bank Acct XX901 debited for Rs 1,50,000.00 on 02-Nov-26; RAMESH K credited. UPI:123400005678. "
     "Call 18002662 for dispute.", {"amount": 150000, "bank": "ICICI", "datetime": "02-11-2026"}),
    ("Your A/c no. XXXXXXXX4321 is debited for Rs.12500.00 on 31-10-2026 and credited to a/c no. XXXXXXXX0007 "
     "(IMPS Ref no 100020003000). -Axis Bank", {"amount": 12500, "utr": "100020003000", "bank": "Axis Bank"}),
    ("Sent Rs.2,25,000.00 From Indian Bank A/C *1111 To loan.help@paytm On 30/10/26 Ref 600011112222 Not You? "
     "Call 18004251400", {"amount": 225000, "utr": "600011112222", "bank": "Indian Bank",
                          "suspect_upi": "loan.help@paytm"}),
    ("Canara Bank: Rs.49,999.00 paid thru A/C XX2222 on 29-10-26 10:15:33 to TASK REWARDS, UPI Ref 998877660011. "
     "Avl Bal Rs.1,000.50", {"amount": 49999, "utr": "998877660011", "bank": "Canara Bank",
                             "datetime": "29-10-2026 10:15"}),
    ("Kotak Bank: Rs 100500 transferred from a/c XX3333 to 9000090000@kotak on 28-10-2026. UTR: 777788889999",
     {"amount": 100500, "utr": "777788889999", "bank": "Kotak"}),
    ("IOB: Your a/c XX4444 debited INR 5000 on 2026-11-01 via UPI. Ref No: 314159265358",
     {"amount": 5000, "utr": "314159265358", "bank": "Indian Overseas Bank", "datetime": "01-11-2026"}),
    ("Amt Sent Rs.700.00 From HDFC Bank A/C *9999 To SHOP On 01-11 Ref 271828182845 Not You?",
     {"amount": 700, "utr": "271828182845", "bank": "HDFC"}),
    ("Rs 2000 debited from your SBI a/c ending 5555 on 01Nov26 at 9:05 PM. UPI Ref 112233445566",
     {"amount": 2000, "utr": "112233445566", "bank": "SBI", "datetime": "01-11-2026 21:05"}),
    ("PNB: A/c XX6666 Dr INR 15,000.00 on 30-10-26 RRN 223344556677", {"amount": 15000, "utr": "223344556677",
                                                                      "bank": "PNB"}),
    ("Bank of Baroda: Rs.8,000 debited A/c ..7777 on 25-10-2026 Txn ID 334455667788",
     {"amount": 8000, "utr": "334455667788", "bank": "Bank of Baroda"}),
    ("Union Bank: INR 3,500.00 debited from A/C XX8888 UTR 445566778899 dt 24/10/2026",
     {"amount": 3500, "utr": "445566778899", "bank": "Union Bank"}),
    ("₹10,000 sent to fake.kyc@axl from your account. UPI Ref No. 556677889900",
     {"amount": 10000, "utr": "556677889900", "suspect_upi": "fake.kyc@axl"}),
    ("You have paid Rs.999 to winner.prize@ibl. UPI transaction ID 667788990011",
     {"amount": 999, "utr": "667788990011", "suspect_upi": "winner.prize@ibl"}),
    ("Rs. 4,500.00 debited via UPI on 23-10-2026 14:45. Ref 778899001122. Bal Rs 12,000 -ICICI",
     {"amount": 4500, "utr": "778899001122", "datetime": "23-10-2026 14:45", "bank": "ICICI"}),
    ("Avl Bal Rs 50,000. Rs 1,200 debited from A/c XX1212 Ref No 889900112233",
     {"amount": 1200, "utr": "889900112233"}),
    ("HDFC Bank: Rs 30000 debited from a/c **1313 on 22-10-26 to a/c **0001 IMPS Ref No 990011223344",
     {"amount": 30000, "utr": "990011223344", "bank": "HDFC"}),
    ("SBI UPI: Paid INR 600.00 to scanner.qr@ybl Ref:101112131415 on 21/10/26",
     {"amount": 600, "utr": "101112131415", "bank": "SBI", "suspect_upi": "scanner.qr@ybl"}),
    ("Txn of INR 7,250.00 done on Axis Bank card XX1414 at ONLINE STORE on 20-10-26. Ref 202122232425",
     {"amount": 7250, "utr": "202122232425", "bank": "Axis Bank"}),
    ("Money transferred! Rs.1,00,000 to invest.gain@upi on 19 Oct 2026 UPI Ref 303132333435",
     {"amount": 100000, "utr": "303132333435", "suspect_upi": "invest.gain@upi", "datetime": "19-10-2026"}),
    ("Dear user Rs 250 debited. UTR is 404142434445. Canara Bank", {"amount": 250, "utr": "404142434445",
                                                                    "bank": "Canara Bank"}),
    ("Your account XX1515 debited Rs.18,000 on 18-10-2026 11:11. Txn No 505152535455 -Kotak",
     {"amount": 18000, "utr": "505152535455", "bank": "Kotak", "datetime": "18-10-2026 11:11"}),
    ("Rs 2,500 debited A/c XX1616 Ref No 606162636465. Query? email care@icicibank.com",
     {"amount": 2500, "utr": "606162636465"}),
    ("INR 60,000.00 debited from A/c 1717 on 17-10-26. Transaction Ref 707172737475. -Indian Bank",
     {"amount": 60000, "utr": "707172737475", "bank": "Indian Bank"}),
]


@pytest.mark.parametrize("sms,expected", CASES)
def test_sms_formats(sms, expected):
    got = parse_sms(sms)
    for k, v in expected.items():
        assert k in got, (k, got)
        assert got[k].value == v, (k, got[k])
        assert got[k].source == "sms"


def test_email_is_not_vpa():
    got = parse_sms(CASES[23][0])
    assert "suspect_upi" not in got


def test_never_returns_full_account_number():
    got = parse_sms("Rs 100 debited from A/c 123456789012345 Ref 111122223333")
    assert "victim_account_last4" not in got or len(str(got["victim_account_last4"].value)) == 4
    assert all("123456789012345" not in str(f.value) for f in got.values())


def test_empty():
    assert parse_sms("") == {}
    assert parse_sms("   ") == {}


def test_balance_not_taken_as_amount():
    got = parse_sms("Avl Bal Rs 50,000. Rs 1,200 debited Ref No 889900112233")
    assert got["amount"].value == 1200


def test_sms_datetime_helper():
    assert sms_datetime("01-11-2026 15:02").hour == 15
    assert sms_datetime("01-11-2026").day == 1
    assert sms_datetime("garbage") is None

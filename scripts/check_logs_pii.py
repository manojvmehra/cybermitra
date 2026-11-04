"""Definition-of-done check: no raw PII in log files.

    python scripts/check_logs_pii.py [logs/]
Fails (exit 1) on any Indian mobile number, 12-digit UTR, Aadhaar-like 4-4-4, card-like 16 digits,
UPI ID or rupee amount found unmasked in *.log files.
"""

import re
import sys
from pathlib import Path

PATTERNS = {
    "mobile": re.compile(r"(?<!\d)(?:\+?91[ -]?)?[6-9]\d{4}[ -]?\d{5}(?!\d)"),
    "utr_or_aadhaar": re.compile(r"(?<!\d)\d{4}[ -]?\d{4}[ -]?\d{4}(?!\d)"),
    "card": re.compile(r"(?<!\d)(?:\d[ -]?){16}(?!\d)"),
    "upi": re.compile(r"\b[\w.\-]{3,}@(?:ybl|okaxis|okhdfcbank|oksbi|okicici|paytm|upi|ibl|axl|apl|kotak)\b"),
    "amount": re.compile(r"(?:₹|Rs\.?|INR)\s?\d[\d,]{2,}", re.I),
}


def main(root: str = "logs") -> int:
    files = sorted(Path(root).glob("**/*.log*"))
    if not files:
        print(f"No log files under {root}/ (set LOG_FILE=logs/app.log and run a session first).")
        return 2
    hits = 0
    for f in files:
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for name, rx in PATTERNS.items():
                if rx.search(line):
                    hits += 1
                    print(f"{f}:{n}: {name}")  # location only: never print the value itself
    print(f"{len(files)} file(s) checked, {hits} PII hit(s).")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))

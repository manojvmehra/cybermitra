# NEXT_STEPS sources

Every guidance line the app speaks at the end of a call (`NS_*` in `app/dialog/prompts.py`) needs an
official source here before submission. A line counts as sourced only when its id is added to
`prompts.NEXT_STEPS_SOURCED`. Until then the caller page shows it with a **"draft guidance"** tag
(DEMO_MODE), and `tests/test_packet.py` checks that the tag follows that set.

**Status (4 Nov 2026): no line is verified yet.** The candidates below came from a web search. Most results
were secondary write-ups, so a team member must open each official page, confirm the wording supports the
line, record the date checked, and only then add the id to `NEXT_STEPS_SOURCED`.

| id | Line (en) | Candidate official source | What to confirm | Verified |
|---|---|---|---|---|
| `NS_CALL_BANK` | Call your bank's helpline now, report the fraud, and ask them to block your card and UPI. | RBI, *Customer Protection – Limiting Liability of Customers in Unauthorised Electronic Banking Transactions* (RBI/2017-18/15, 6 Jul 2017): https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=11040 | Customers must notify the bank at the earliest; liability depends on how fast it is reported; the bank must act at once to stop further unauthorised debits. Check the exact day limits in the RBI text, not secondary summaries. | ☐ |
| `NS_KEEP_EVIDENCE` | Do not delete SMS, call logs or chats. Take screenshots. | cybercrime.gov.in (complaint filing guidance / FAQ) | The portal asks for transaction details and evidence (screenshots, messages). Quote the exact page. | ☐ |
| `NS_CHANGE_PIN` | Change your net-banking password and UPI PIN from your own phone. | Candidates: RBI "RBI Kehta Hai" awareness material (https://rbikehtahai.rbi.org.in), CERT-In advisories (https://www.cert-in.org.in), or the I4C awareness handle (Cyber Dost). | An official recommendation to reset credentials after compromise. | ☐ |
| `NS_RECOVERY_SCAM` | Anyone who offers to recover your money for a fee is another scam. | Candidates: I4C / Cyber Dost advisories on "fund recovery" fraud, state police cyber-crime advisories (Tamil Nadu: https://cybercrime.tn.gov.in, check it exists). | An official warning about fee-based "recovery" offers. | ☐ |

## Helpline numbers shown on screen

| Number | Shown where | Candidate official source | Verified |
|---|---|---|---|
| 1930 | header, every handoff | https://cybercrime.gov.in | ☐ |
| Tele-MANAS 14416 (alt. 1-800-891-4416) | wellbeing handoff | https://telemanas.mohfw.gov.in (Ministry of Health and Family Welfare) | ☐ |

## How to mark a line verified

1. Open the official page and find the sentence that supports the line.
2. Fill in the row: exact URL, the supporting quote (short), and the date checked.
3. Add the id to `NEXT_STEPS_SOURCED` in `app/dialog/prompts.py`; the "draft guidance" tag disappears for it.
4. If the source says something different, change the prompt (both `ta` and `en`) to match the source.

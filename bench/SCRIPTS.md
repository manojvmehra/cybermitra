# Acted benchmark: how to record

Every number below is fake. Speakers are consenting team members acting a role. Never use a real number,
account, Aadhaar or PAN, and never record a real call. Prefer more speakers over more conditions, keep the
delivery emotional and natural, and code-mix freely.

## Steps

1. `python bench/make_manifest.py --speakers spk1,spk2,spk3 --improvised spk1:S2_UPI_COLLECT,spk2:S5_JOB_TASK,spk3:S6_LOAN_APP`
   writes the ground truth and the clip list. Each speaker needs at least one improvised script: speak in your
   own words, using the same fake numbers from a card.
2. Record each clip to `bench/corpus/<clip_id>.wav` (or `.m4a`, `.mp3`, `.ogg`, `.flac`, `.webm`), under 25 s.
3. Put a few recorded street or room noise files in `bench/noise/*.wav`. Without them the `snr` conditions are skipped.
4. `python bench/check_corpus.py` lists what is missing or wrong, with no API calls. Fix until it says `READY`.
5. `python bench/augment.py`, then `python bench/run_benchmark.py`. This asks first if it needs over 50 live STT calls.
6. `python bench/simulate_calls.py`, then `python bench/report.py`, which writes `RESULTS.md` and updates the README.

## Clips for each call

For `s1_spk2`: `s1_spk2_narrative` (the whole story), then one clip per answer, spoken as if asked that question:

| clip | say |
|---|---|
| `_amount_1` | the amount of debit 1 |
| `_time_1` | the time phrase below for debit 1 |
| `_utr_1` | the 12-digit UTR of debit 1 |
| `_bank` | your bank |
| `_phone` | the suspect's number |
| `_yes` | any "yes": "aama", "sari" |
| `_no` | any "no": "illa", "thappu" |
| `_correction` | "illa, kadaisi number ettu" (no, the last digit is eight) |

Scripts with several debits have `_amount_2`, `_time_2`, `_utr_2`, and so on. With `--all-slots` there are also
clips for district, name, mobile, payment mode and "called the bank?". The sextortion script is the story only.

## Scripts

Pretend the call is at noon on 5 Nov 2026, so "nethu" means 4 Nov.

| id | gist (your own words, Tamil/Tanglish) | debits (amount, UTR, time phrase) | suspect phone | bank |
|---|---|---|---|---|
| S1_OTP_BANK | "SBI-ல இருந்து கால், KYC update, OTP கேட்டாங்க", money went twice | ₹40,000, 4306 1982 7418, *nethu madhiyam moonu mani*; ₹10,000, 4306 1982 7419, *nethu madhiyam naalu mani* | 98765 43218 | SBI |
| S2_UPI_COLLECT | OLX buyer sent a collect request, "pin pottaen" | ₹25,000, 5123 0000 4567, *innaikku kaalaila pathu mani* | 91234 56780 | HDFC |
| S3_DIGITAL_ARREST | "CBI video call, parcel-ல drugs", paid three times | ₹1,00,000, 6000 1111 2222, *nethu kaalaila pathinonnu mani*; ₹75,000, 6000 1111 2223, *nethu madhiyam pannendu mani*; ₹50,000, 6000 1111 2224, *nethu madhiyam oru mani* | 80000 12345 | Indian Bank |
| S4_INVESTMENT | Telegram trading group, "ஒன்றரை லட்சம்" invested | ₹1,50,000, 1234 0000 5678, *nethu saayangaalam* | 70000 98765 | ICICI |
| S5_JOB_TASK | Online task job | ₹49,999, 9988 7766 0011, *innaikku kaalaila* | 60000 11122 | Canara Bank |
| S6_LOAN_APP | Loan app processing fee | ₹12,500, 1000 2000 3000, *nethu raathiri* | 99887 76655 | Axis Bank |
| S7_FAKE_CARE | Searched "customer care", AnyDesk | ₹1,00,500, 7777 8888 9999, *oru mani neram munnadi* | 90000 90000 | Kotak |
| S8_SEXTORTION_HANDOFF | Morphed-photo threat, no money. Must hand off, collects nothing | — | — | — |

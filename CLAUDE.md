# CyberDesk TN — Claude Code Build Prompt (Backend-first)

> Save as `CLAUDE.md` at the repo root.
> Two static HTML pages (caller + operator). All effort goes into the backend, Gnani integration, number pipeline, call state machine, review queue, and benchmark.

---

## 0. ROLE AND GOAL

You are building **CyberDesk TN**, an **AI-first voice intake agent for Tamil Nadu's 1930 cyber-fraud helpline overflow**, for the Gnani AI "Great Indian AI Internship Challenge 2026" (deadline **10 Nov 2026, 23:59 IST**).

**What it does**

1. A victim speaks Tamil / Tanglish / English (caller page, separate device).
2. The AI **handles the whole call**: takes the story, captures **every transaction** (UTR, amount, time), the victim's bank and the suspect's details, converts every number **deterministically in code**, reads digits back in chunks with **Gnani Timbre**, and lets the caller correct them.
3. It closes the call with **next-steps guidance** in the caller's language and a text summary with a draft reference ID.
4. It pushes a **verified Complaint Packet** (CFCFRMS field order) to an **operator review queue**. A human operator reviews and **approves in ~30 s** instead of typing for ~20 min.
5. A call goes to a human **only** when the caller asks, the AI cannot understand, or the case is non-financial or an emergency. The handoff is **warm**: the operator receives the transcript and the partial packet, so the caller never repeats the story.

**What it does NOT do:** file on NCRP/CFCFRMS, contact banks or police, freeze or recover money, or auto-approve anything.

**Core rules of the whole system**
- *A language model never decides a digit. Code converts digits. A human confirms digits.*
- *The AI handles the call. A human approves the complaint.*

---

## 1. HARD CONSTRAINTS (NON-NEGOTIABLE)

1. **Synthetic data only.** Challenge rules forbid real phone numbers, account numbers, Aadhaar, PAN or recorded real calls. All test audio is acted (scripted or improvised role-play) by consenting people using obviously fake numbers.
2. **No secrets in git.** `GNANI_API_KEY` only via `.env` (`.env` in `.gitignore`, ship `.env.example`).
3. **Never store audio to disk in the live app.** Audio lives in memory for the request only. (The acted benchmark corpus lives under `bench/`.)
4. **Never log raw PII.** Mask phone/UTR/amount in every log line (`98•••••210`, `4306••••7418`).
5. **Never ask for OTP, PIN, CVV, password, full account number, Aadhaar or PAN.** If the user speaks one, drop it and do not echo it back.
6. **Never fabricate benchmark numbers.** All metrics are computed by `bench/` scripts from real API output. No target tables in the README.
7. **Async + bounded concurrency.** Gnani may return `429 RATE_LIMITED` ("Only 1 active request is allowed at a time"). Wrap every Gnani call in a global `asyncio.Semaphore(GNANI_MAX_CONCURRENCY)` (default 1) with exponential backoff + jitter (max 4 tries).
8. **Cache every Gnani call** by SHA-256 of (audio bytes or text) + all request params. Cache hits never hit the network.
9. App name is a config value (`APP_NAME`, default `CyberDesk`). Never hardcode it.
10. **No autonomous action.** Nothing leaves the system without an operator `approve`. Approval only changes packet status. It never submits anywhere.
11. **Queue fairness.** The amount **never** affects queue order. Order uses only *operator-visible, caller-confirmed* fields (§6.15). Log every reorder with its reason.
12. **Honest labels.** The draft reference ID is `CD-DRAFT-xxxx` and is never presented as an NCRP acknowledgement. Handoff in the demo is labelled "simulated transfer". Phone calls (§6.16) are labelled "experimental telephony".

---

## 2. VERIFIED GNANI API FACTS (from docs.gnani.ai, last verified Aug 2026)

**First action:** fetch `https://docs.gnani.ai/llms.txt` and re-verify everything below. If anything differs, the docs win: update the `gnani/` clients and note the change in `docs/API_NOTES.md`.

### 2.1 Common
- Base URL: `https://api.vachana.ai`
- Auth header: `X-API-Key-ID: <key>` (optional `X-API-Request-ID`: use session id + turn number).
- A Python SDK exists (`pip install gnani-vachana`). **Use raw `httpx` instead** so you control caching, retries and params. Use the SDK for the smoke test only, if at all.
- Gateway errors (401/402/403/429) use `{"detail": {"error_code", "message", "status_code"}}`. Endpoint errors use `{"success": false, "error": {"type", "message"}}`. 422 uses `{"detail": [...]}`. Parse all three shapes.

### 2.2 STT — Gnani Prisma (REST)
- `POST /stt/v3`, `multipart/form-data`
- `audio_file` (required): WAV/MP3/OGG/FLAC/AAC/M4A, **max 30 s**. The server resamples to 16 kHz mono.
- `language_code` (required): Tamil = `ta-IN`, English = `en-IN`.
- `model`: omit → **Prisma v2.5** (`model: "gnani-prisma-v2.5"`). `prisma-v3.0` → v3.0.
- `format`: `verbatim` (default) | `transcribe` (ITN: numbers → digits) | v3.0 only: `codemix`, `transliterate`.
- v2.5: `bias_list` (≤100 single letter-only words) + `bias_score` ∈ {0, 0.5, 1.0, 1.5, 2.0}.
- v3.0: `language_code` may be `indic-auto` or a comma list of ≤4 (`ta-IN,en-IN`). Also takes `keyterms` (≤200), `topic` (≤1600 chars) and `previous_text` (last 600 chars).
- `enable_substitution` + `substitution_map` (≤10 rules) on both.
- Response v2.5: `{success, request_id, transcript, model, processing_time, end_to_end_latency, output: {literal}}`. **`output.literal` is the pre-ITN transcript**, so with `format=transcribe` one call gives both the ITN digits and the spoken words.
- Response v3.0: adds `detected_language_code`, and may include `truncated: true`. No `output.literal`.
- An empty transcript `""` is not an error. v3.0 may return `504 UPSTREAM_TIMEOUT` → retry once.
- Realtime WebSocket and Batch STT exist but are **not needed**. The design is push-to-talk + REST.

### 2.3 TTS — Gnani Timbre (REST)
- `POST /api/v1/tts/inference`, JSON:
```json
{ "text": "...", "voice": "<from catalog>", "model": "timbre-v2.5",
  "language": "ta-IN", "speed": 0.9,
  "audio_config": {"sample_rate": 24000, "num_channels": 1, "sample_width": 2,
                   "encoding": "linear_pcm", "container": "wav"} }
```
- Returns raw audio bytes. Timbre v2.0 is deprecated → **use `timbre-v2.5`** (v3.0 as a config option).
- **Don't guess voice names.** Fetch the catalog (`/api/TTS/available-voices`) and store `TTS_VOICE_TA` / `TTS_VOICE_EN`.
- `speed` ranges 0.85–1.15. Use **0.9** for read-backs.
- Timbre groups 10-digit phones 3-3-4 and may compress repeats, so **read-back sends digit WORDS separated by commas** (§6.5).
- Telephony output (`container: "mulaw"`, 8 kHz) is available for the phone path (§6.16).

### 2.4 LLM — Gnani Evon v3.3 (OPTIONAL)
- **Not on the Gnani API platform.** It is open weights on Hugging Face only (`gnani/gnani-evon-v3.3-30B-A3B`): hybrid Mamba MoE, ~31.7B params, BF16, 128K context, Apache-2.0, served via vLLM on an A100/H100 80GB.
- `EVON_MODE=off|openai_compat` (default **off**). The app must work fully with Evon off. Evon is an *enhancer* for narrative span-finding and fraud-type classification, **never for digits**.

### 2.5 Challenge rule facts that affect design
- Name every Gnani model used. Prisma + Timbre satisfy "at least one Gnani model"; Evon is a bonus.
- **One award max per team.** Primary target: **Mixed Vibes** (best code-mixed voice build). "Noise Canceller" is judged on noisy *telephone* audio, so the benchmark must include 8 kHz telephone-band conditions.
- Honest limitations beat faked demos.

---

## 3. ARCHITECTURE

```
CALLER DEVICE (phone browser)                    OPERATOR DEVICE (laptop browser)
static/caller.html                               static/operator.html
mic + silence stop, SMS paste, keypad            review queue, packet view, Approve/Edit/Reject,
   │ multipart audio / JSON                      "Take call" for handoffs
   ▼                                                ▲ SSE /api/events  │ JSON
FastAPI (app/main.py) ─────────────────────────────┘                  │
 ├── audio.normalize() → ffmpeg → 16 kHz mono WAV                     │
 ├── gnani.stt.transcribe() ──► Prisma (cached, semaphore, retry)     │
 ├── nlp.numbers / nlp.timeparse / nlp.sms_parser  (deterministic)    │
 ├── nlp.extractor (rules; Evon optional, spans only)                 │
 ├── nlp.validators / nlp.yesno / nlp.safety                          │
 ├── dialog.state_machine  (per-call FSM, multi-transaction loop)     │
 ├── dialog.readback → gnani.tts.synthesize() ──► Timbre (cached)     │
 ├── dialog.packet  → Complaint Packet + Victim Summary               │
 └── queue.store + queue.priority  ◄──────────────────────────────────┘
State: in-memory dicts (sessions TTL 30 min, packets TTL 24 h). No DB.
```

**Key design decisions (implement exactly):**
1. **The slot is known from the question.** In GAP_FILL the system asks for ONE field at a time, so the answer belongs to that field. Narrative extraction (the first free-form turn) is best-effort; gap-fill is deterministic.
2. **Dual-channel number reading on Prisma v2.5.** One `format=transcribe` call returns `transcript` (ITN) + `output.literal`. Parse both independently: if they agree → `confidence=high`; if they disagree or only one parses → `confidence=low`. Both still go to read-back. For low confidence, read back the literal parse and offer the numpad first.
3. **Paste-first for UTR/amount/time.** Values parsed from a pasted bank SMS get `source="sms"`, are shown on screen and are not re-confirmed by voice (still editable). **One SMS paste = one transaction.**
4. **Buttons beat voice for confirmation.** ✓/✗ is authoritative.
5. **Any "no" wins.** An ambiguous voice answer counts as "no" and the chunk is re-asked.
6. **Max 2 repair attempts per field**, then `status="unconfirmed"`. The packet shows "⚠ verify" and the operator sees it highlighted.
7. **One transaction by default.** `MAX_TXNS` defaults to 1: after one confirmed transaction the call moves straight to the case fields, with no "any other transaction?" question. If the caller mentioned more, the packet says so (`reported_txn_count`) and the AI says an officer will add them. With `MAX_TXNS` above 1 the multi-transaction loop runs, asking *"Innoru transaction irukka?"* after each one.
8. **AI-first, human by exception.** A completed call → `packet.status="ready_for_review"`. Escalation → `packet.status="needs_human"` with reason, masked transcript and partial fields (warm handoff).
9. **Queue order never uses the amount** (§6.15).
10. **Rank only on confirmed fields.** An unconfirmed time sorts as "unknown" (arrival order), never as "fresh".

---

## 4. REPO LAYOUT (create exactly this)

```
cyberdesk/
├── CLAUDE.md
├── README.md                      # setup, run, architecture, HONEST measured results
├── .env.example
├── pyproject.toml                 # python 3.11, ruff, pytest config
├── requirements.txt
├── Makefile                       # setup, run, test, probe, prerender, bench, sim, lint
├── Dockerfile                     # includes apt-get install -y ffmpeg
├── app/
│   ├── main.py
│   ├── config.py
│   ├── logging_utils.py           # structured JSON logs + mask()
│   ├── audio.py
│   ├── cache.py
│   ├── ratelimit.py
│   ├── gnani/
│   │   ├── http.py
│   │   ├── stt.py
│   │   ├── tts.py
│   │   └── evon.py                # optional
│   ├── nlp/
│   │   ├── lexicon_ta.py
│   │   ├── numbers.py
│   │   ├── timeparse.py           # NEW: relative/absolute Tamil-English time → estimate
│   │   ├── sms_parser.py
│   │   ├── extractor.py
│   │   ├── validators.py
│   │   ├── yesno.py
│   │   └── safety.py
│   ├── dialog/
│   │   ├── models.py              # Field, Txn, Session, Packet, QueueItem
│   │   ├── prompts.py             # all prompts incl. NEXT_STEPS_*, ta + en
│   │   ├── readback.py
│   │   ├── state_machine.py
│   │   └── packet.py              # NEW: Complaint Packet + Victim Summary rendering
│   ├── queue/
│   │   ├── store.py               # NEW: in-memory packets, status transitions, audit log
│   │   └── priority.py            # NEW: fair ordering (§6.15)
│   └── api/
│       ├── routes_caller.py
│       ├── routes_operator.py     # NEW
│       ├── events.py              # NEW: SSE broadcaster
│       └── schemas.py
├── static/
│   ├── caller.html                # vanilla JS, no build
│   └── operator.html              # vanilla JS, no build
├── scripts/
│   ├── smoke_gnani.py
│   ├── probe_prisma_formats.py
│   └── prerender_prompts.py
├── bench/
│   ├── corpus/                    # acted clips (audio gitignored; manifest committed)
│   ├── manifest.jsonl             # per-call: turns[{clip_id, slot, truth}], call_truth{...}
│   ├── noise/
│   ├── augment.py                 # clean, snr10, snr5, tel8k, snr10_tel8k
│   ├── run_benchmark.py           # field accuracy
│   ├── simulate_calls.py          # NEW: full-call FSM runs → containment, handling time
│   └── report.py                  # writes bench/RESULTS.md with n + Wilson 95% CI
├── tests/
│   ├── test_numbers_ta.py         # ≥120 cases
│   ├── test_timeparse.py          # NEW ≥40 cases
│   ├── test_sms_parser.py         # ≥25
│   ├── test_validators.py
│   ├── test_yesno.py
│   ├── test_readback.py
│   ├── test_state_machine.py
│   ├── test_priority.py           # NEW
│   ├── test_packet.py             # NEW
│   └── test_api.py                # caller + operator + SSE, Gnani mocked
└── docs/
    ├── API_NOTES.md
    ├── ARCHITECTURE.md
    └── NEXT_STEPS_SOURCES.md      # NEW: official source for every victim guidance line
```

---

## 5. CONFIG (`app/config.py`, pydantic-settings)

```
GNANI_API_KEY=
GNANI_BASE_URL=https://api.vachana.ai
GNANI_MAX_CONCURRENCY=1
GNANI_TIMEOUT_S=30

STT_MODEL=v2.5                 # v2.5 | v3.0 (decided by probe)
STT_LANGUAGE=ta-IN
STT_FORMAT=transcribe
STT_BIAS_SCORE=1.0
STT_V3_TOPIC=Cyber fraud complaint: bank, UPI, amount, phone number, transaction ID, time

TTS_MODEL=timbre-v2.5
TTS_VOICE_TA=
TTS_VOICE_EN=
TTS_SPEED_PROMPT=1.0
TTS_SPEED_READBACK=0.9
TTS_SAMPLE_RATE=24000

EVON_MODE=off
EVON_BASE_URL=http://localhost:8000/v1
EVON_MODEL=model
EVON_TIMEOUT_S=8

APP_NAME=CyberDesk
SESSION_TTL_S=1800
PACKET_TTL_S=86400
MAX_CLIP_S=25                  # largest piece sent to Prisma in one request
MAX_TURN_S=300                 # safety cap on one spoken turn; longer turns are split into MAX_CLIP_S pieces
MAX_TXNS=1
MAX_TURNS_PER_CALL=60
SILENCE_HANDOFF_COUNT=2
QUEUE_MAX_WAIT_S=300           # an item waiting longer than this jumps to the top (FIFO among overdue)
OPERATOR_TOKEN=                # shared secret for operator.html + /api/operator/*
DAILY_SESSION_CAP=40
PER_IP_SESSIONS_PER_HOUR=6
CACHE_DIR=.cache
DEMO_MODE=true                 # banner: "demo only — do not enter real details"

TWILIO_ENABLED=false           # §6.16; routes are not mounted unless true
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=
TWILIO_PUBLIC_URL=             # e.g. https://abc.ngrok-free.app; empty = taken from the request headers
TWILIO_LANG=ta                 # the language of phone calls
```

---

## 6. MODULE SPECS

### 6.1 `gnani/http.py`
- One module-level `httpx.AsyncClient(timeout=GNANI_TIMEOUT_S)`.
- `async def call(method, path, *, files=None, data=None, json=None, expect="json"|"bytes", request_id)`.
- Semaphore around the network call. Retry on 429/500/503/504/`TransportError` with backoff `0.5*2**n + rand(0,0.3)`, max 4 tries. No retry on 400/401/402/403/422.
- Raise `GnaniError(status, code, message, request_id)`, normalising the three error shapes.
- Track metrics (`calls_by_endpoint`, `cache_hits`, `latency_ms`) for `/api/metrics`.

### 6.2 `gnani/stt.py`
```python
@dataclass
class SttResult:
    text: str; literal: str | None; model: str
    detected_language: str | None; truncated: bool; latency_ms: int; cached: bool
```
- `async def transcribe(wav_bytes, *, profile, bias_words=None, context=None) -> SttResult`
- v2.5 omits `model` and sends `bias_list` + `bias_score`. v3.0 sends `model=prisma-v3.0`, `keyterms`, `topic`, `previous_text` (= the last assistant prompt).
- Cache key = sha256(wav) + sorted params.
- Default `bias_list` (letters only): `["SBI","HDFC","ICICI","Axis","Canara","Indian","IOB","Kotak","PhonePe","GPay","Paytm","UPI","UTR","OTP","KYC","IMPS","NEFT"]` + Tamil aliases from `lexicon_ta.BANK_ALIASES`. Validate letters-only and log any dropped entries.

### 6.3 `gnani/tts.py`
- `async def synthesize(text, *, lang, speed) -> bytes`. Cache under `CACHE_DIR/tts/<hash>.wav`; serve at `/api/audio/<hash>.wav`.
- `scripts/prerender_prompts.py` renders every static prompt in both languages.

### 6.4 `nlp/numbers.py` + `nlp/lexicon_ta.py` (THE CORE — test hardest)

Inputs arrive in four shapes; handle all:
1. **ITN digits**: `₹50,000`, `50000`, `9876543210`, `5,20,000`.
2. **Tamil script**: `ஐம்பதாயிரம்`, `ஒன்றரை லட்சம்`, `ஒன்பது எட்டு ஏழு…`.
3. **Romanised Tanglish**: `aimbadhaayiram`, `onnara latcham`, `rendu latchathi irubathanju aayiram`.
4. **English / shorthand**: `fifty thousand`, `50k`, `1.5 lakh`, `one and a half lakh`, `double nine triple eight`.

```python
def normalise_text(s: str) -> str
def parse_amount(s: str) -> ParseResult           # value: int rupees | None, spans, method, warnings
def parse_digit_string(s: str, expected_len: int | None) -> ParseResult
def find_number_spans(transcript: str) -> list[Span]
```

Lexicon (Tamil script + romanisations + colloquial). **Karthikeyan (native speaker) reviews every entry and adds the variants Prisma actually emits (see the probe report).** An existing tested prototype (`cybermitra_core.py`: romanised parser, digit parser, validators, read-back, yes/no) can seed this module. Port it into these files and extend it; don't rewrite it from scratch.

| Value | Tamil script (formal / colloquial) | Romanised variants |
|---|---|---|
| 0 | பூஜ்ஜியம், சைபர், ஜீரோ | poojyam, poojiyam, saibar, zero, jeero |
| 1 | ஒன்று, ஒண்ணு, ஒரு | onru, onnu, oru, one |
| 2 | இரண்டு, ரெண்டு | irandu, rendu, randu, two |
| 3 | மூன்று, மூணு | moonru, moonu, munu, three |
| 4 | நான்கு, நாலு | naangu, naalu, nalu, four |
| 5 | ஐந்து, அஞ்சு | ainthu, aindhu, anju, anchu, five |
| 6 | ஆறு | aaru, aru, six |
| 7 | ஏழு | ezhu, elu, seven |
| 8 | எட்டு | ettu, eight |
| 9 | ஒன்பது | onbadhu, onbathu, ombadhu, nine |
| 10 | பத்து | pathu, padhu, ten |
| 20–90 | இருபது, முப்பது, நாற்பது, ஐம்பது, அறுபது, எழுபது, எண்பது, தொண்ணூறு | irubadhu, muppadhu, naarpadhu, aimbadhu, arubadhu, ezhubadhu, enbadhu, thonnooru |
| 100–900 | நூறு, இருநூறு, முந்நூறு, நானூறு, ஐந்நூறு, அறுநூறு, எழுநூறு, எண்ணூறு, தொள்ளாயிரம் | nooru, irunooru, munnooru, naanooru, ainnooru, arunooru, ezhunooru, ennooru, thollaayiram |
| 1000 | ஆயிரம் (ஆயிரத்து) | aayiram, ayiram, aayirathu |
| 1e5 | லட்சம், லட்சத்து, லட்சத்தி | latcham, lakh, latchathu, latchathi |
| 1e7 | கோடி | kodi, crore |
| ½ | அரை (ஒன்றரை 1.5, ரெண்டரை 2.5) | arai, onnara, rendara |
| ¼, ¾ | கால், முக்கால் | kaal, mukkaal |

Rules:
- **Sandhi splitting:** `ஐம்பதாயிரம்` = 50,000; `இருபத்தைந்து`/`இருபத்தி ஐந்து` = 25; `நூற்றி ஐம்பது` = 150. Use a greedy longest-match tokenizer over a stem table, not regex soup.
- Combining forms (`-த்து`, `-த்தி`, `-ற்றி`) mean "and continue".
- Indian multiplier stack: `(a×1e7)+(b×1e5)+(c×1000)+(d×100)+e`. Fractions are valid only before a multiplier.
- `k` means ×1000. `₹`, `rupees`, `ரூபாய்`, `rubaa` are unit markers.
- Digit strings: expand `double X`/`டபுள் X`/`triple X` and ignore fillers. Never merge two separate spoken numbers; return both spans.
- **Ambiguity → warning, not a guess.**
- `method ∈ {"itn_digits","tamil_words","roman_words","english_words","mixed"}`.

Tests (≥120): every table row; 30 compound amounts (2,25,000 / 1,50,000 / 49,999 / 1,00,500 / 12,34,567); 20 phone strings (double/triple, mixed Tamil+English); 20 UTRs; 15 adversarial (fillers, `rendu moonu` = "a couple" → no amount); round-trip `render_digits_ta(parse(x)) == x`.

### 6.5 `dialog/readback.py`
- Phone 5+5. UTR 4+4+4. UPI ID: local part chunked by 4, then "at", then the handle letter by letter. Amount: read as words + "ரூபாய்", and also shown as digits on screen. **Time: read as a phrase** ("innaikku kaalai pathinonnu mani", today 11 a.m.).
- `render_digits_ta(chunk)` maps each digit to its Tamil word, joined with `", "`; `render_digits_en` does the same in English.
- Templates: ta `"{field_label}: {chunk_words}. சரியா?"`, en `"{field_label}: {chunk_words}. Is that right?"`. For a transaction, prefix `"Transaction {n}: "`.
- Return `ReadbackStep{field, txn_index, chunk_index, chunk_digits, text, audio_url}`.

### 6.6 `nlp/sms_parser.py`
Parse a pasted bank/UPI SMS (synthetic fixtures only):
- UTR/RRN/Ref: a 12-digit run near `UTR|RRN|Ref|Ref No|UPI Ref|Txn ID`.
- Amount: `(?:Rs\.?|INR|₹)\s?([\d,]+(?:\.\d{1,2})?)` near `debited|sent|paid|transferred`.
- Bank from sender/keywords. Datetime formats `dd-mm-yy`, `dd/mm/yyyy`, `ddMonyy`, `HH:MM(:SS)?` (IST).
- Beneficiary VPA: `[\w.\-]{2,}@[a-z]{2,}`.
- Every field gets `source="sms"`, `confidence="high"`, `raw_span`. **Keep only the last 4 digits** of any victim account (`victim_account_last4`).
- One SMS → one `Txn`. Several SMS pasted at once → several `Txn`s (split on blank lines or repeated "debited").

### 6.7 `nlp/extractor.py`
- `extract_narrative(stt, lang) -> NarrativeResult` (rules only):
  - Bank alias match → canonical name.
  - Fraud type enum `{OTP_BANK_CALL, UPI_COLLECT, DIGITAL_ARREST, INVESTMENT, JOB_TASK, LOAN_APP, FAKE_CUSTOMER_CARE, OTHER}`.
  - **Amount candidates: ALL** number spans within ±6 tokens of loss cues (`போச்சு/pochu`, `anuppinen`, `debit`, `cut aachu`, `rubaa`). Several candidates → pre-seed several `Txn`s, each unconfirmed.
  - Suspect phone: a 10-digit span near `call vandhuchu/கால் வந்துச்சு/andha number`. Victim phone only after `en/ennoda/my`.
  - Time phrases → `timeparse.parse_time`.
  - Multi-transaction cues: `rendu thadava` (two times), `moonu transaction`, `again`, `innoru` (another) → set `expected_txn_count`.
- `Candidate{value, confidence, source: "voice_itn"|"voice_literal"|"both"|"evon"|"sms"|"numpad"|"operator", span_text}`.
- **Evon merge (only if enabled):** Evon returns JSON spans that must be exact substrings of the input. Anything that isn't is discarded. Spans go through `numbers.py`; Evon's own digits are never used. On timeout, fall back to rules silently. Temperature 0, `enable_thinking=false`.

### 6.8 `nlp/validators.py`
- Indian mobile: 10 digits starting 6–9; strip `+91`/`91`/`0`.
- UTR/RRN: exactly 12 digits. For 11 or 13 digits, re-ask with the count heard.
- UPI: `^[\w.\-]{2,256}@[a-zA-Z]{2,64}$`.
- Amount: 1 ≤ x ≤ 10,00,00,000. Above ₹10 lakh → an extra confirmation step (this affects confirmation only, never the queue).
- Datetime: not in the future. More than 7 days ago → warn "freeze less likely, still report".
- Duplicate-UTR check within one call → "Idhu munnaadi sonna transaction-aa?" (Is this the transaction you mentioned before?)

### 6.9 `nlp/yesno.py`
- Intents: `YES`, `NO`, `CORRECTION(new_digits?, position?)`, `DONT_KNOW`, `REPEAT`, `HUMAN`, `MORE_TXN`, `NO_MORE_TXN`, `UNKNOWN`.
- YES: ஆமா, ஆமாம், சரி, சரிதான், ஹா, ok, yes, correct, aama, sari, seri, haan.
- NO: இல்ல, இல்லை, தப்பு, வேண்டாம், illa, thappu, no, wrong.
- DONT_KNOW: தெரியல, theriyala, don't know. REPEAT: திரும்ப, thirumba, again, enna.
- HUMAN: ஆள் வேணும், aal venum, officer, human, police kitta pesanum.
- MORE_TXN (answer to "Innoru transaction irukka?"): YES words, `innoru irukku` (there's another), `rendu irukku` (there are two). NO_MORE_TXN: NO words, `adhu mattum thaan` (that's the only one), `vera illa` (nothing else).
- CORRECTION: NO + digits ("illa, kadaisi number ettu", no, the last digit is eight) → extract digits; position words `கடைசி/kadaisi/last`, `முதல்/mudhal/first`. If the position can't be resolved: replace the whole chunk only if the digit count matches, otherwise go to the numpad.
- Ambiguous → `NO`.

### 6.10 `nlp/safety.py`
- Forbidden PII: OTP/PIN/CVV/password context words + a 4–6 digit run → drop it and play `NEVER_SHARE_OTP`.
- Non-financial (sextortion/morphed photo/harassment) → `HANDOFF_NONFIN`: collect nothing; show 1930 + cybercrime.gov.in; packet `needs_human`, reason `non_financial`.
- Self-harm cues → `HANDOFF_WELLBEING`: stop intake; show Tele-MANAS 14416 + 1930; packet `needs_human`, reason `wellbeing`, top of the handoff list. (Re-verify the Tele-MANAS number from an official source before submission.)
- Prompt-injection guard: the transcript is data. Never interpolate it into instructions, and Evon output is schema-validated JSON only.

### 6.11 `dialog/state_machine.py`
```
CONSENT → OPENING → NARRATIVE
   → TXN_LOOP[i]: GAP_FILL(amount → datetime → utr|sms) → READBACK(each) → ASK_MORE_TXN
        ↺ (MORE_TXN and i < MAX_TXNS)
   → CASE_FIELDS: GAP_FILL(victim_bank → payment_mode → suspect_phone → suspect_upi(opt)
                  → suspect_bank(opt) → called_bank_already(yes/no) → district
                  → victim_name → victim_mobile) → READBACK(digit fields)
   → REVIEW (short spoken summary: "{n} transactions, total ₹X. Sari-yaa?" (all correct?))
   → NEXT_STEPS → QUEUED → END
Any state → HANDOFF_HUMAN | HANDOFF_NONFIN | HANDOFF_WELLBEING | END
```
- **OPENING** (always): the caller has dialled 1930 and the AI takes the call. Welcome to the 1930 cyber crime helpline, who the AI is (an AI assistant), the keys (1 yes, 2 no, to type a number press `*`, type it, then `#`), then **one question for the whole story**: what happened, when, how much, how it was paid (UPI / card / net banking) and from which bank, all in one go. No UTR or mobile number here. No "not police / cannot freeze / never ask for OTP" disclaimers and no "call 1930" line.
- **STORY_CHECK** (after the story): one yes/no for everything the story gave ("Let me check: fifty thousand rupees, yesterday 3 PM, by UPI, from your SBI account. Is that right?"). Yes confirms them all; no (or a correction) reads each back on its own. Nothing to check → straight to the questions. Then only what the story left out is asked.
- **Numbers are typed, last.** UTR (for each transaction) and mobile numbers (suspect, then victim) come after every spoken field. They are never asked aloud: the question says "type it, then press #" and opens the keypad. A number already heard in the story is read back instead. An amount is asked by voice; if it cannot be understood, the AI asks the caller to type it.
- **No REVIEW question.** The call ends with one spoken summary ("I have noted …"), "we will send you an SMS with your reference number and next steps", goodbye, and the call ends by itself. The next steps are not spoken: they are in the SMS (the summary card on the caller page, labelled simulated in the demo; on the phone path the AI says no SMS is sent and reads the reference).
- **Pace.** Prompts at Timbre speed 1.15, read-backs at 1.0; the caller page plays at 1.3x (pitch kept), about 1.5x overall for prompts. A pause of 1.2 s ends an answer (2 s during the story).
- **Escalation triggers → HANDOFF_HUMAN:** caller asks for a human; 2 failed repairs on the same field *and* the numpad declined; `SILENCE_HANDOFF_COUNT` empty transcripts; `MAX_TURNS_PER_CALL` reached; 3 consecutive `UNKNOWN` intents.
- On any HANDOFF: build the packet with what exists, `status="needs_human"`, attach `handoff_reason` + masked transcript, push to the queue, emit SSE, and tell the caller "Connecting you to an officer (simulated in demo). Please also call 1930."
- Transitions are pure: `next_state(session, event) -> (session, actions)`. Events: `AUDIO_TURN(stt)`, `SMS_PASTED(text)`, `BUTTON(field, txn, chunk, yes|no)`, `NUMPAD(field, txn, digits)`, `SKIP(field)`, `BACK`, `TIMEOUT`, `OPERATOR_TAKEOVER`.
- **BACK** undoes the last answer and asks that question again. It restores the fields from before that answer, so a value can only return to pending or empty, never become confirmed. Turn counts and the transcript stay. It is not available after the packet is pushed.
- Actions: `SpeakPrompt`, `ShowReadback`, `UpdateFields`, `ShowSummary`, `PushPacket`.
- 100% unit-testable with no network.

### 6.12 `nlp/timeparse.py` (NEW)
`def parse_time(s: str, now: datetime) -> TimeResult{value: datetime|None, precision: "minute"|"hour"|"part_of_day"|"day"|None, method, warnings}`

Must handle (Tamil script + Tanglish + English):
- Relative: `12 nimisham munnadi`, `12 minutes munnadi`, `arai mani nerathukku munnadi` (30 min ago), `oru mani neram munnadi` (1 h ago), `rendu mani neram aachu` (it's been 2 h), `ippo thaan`/`just now` (≈ now−5 min, precision minute).
- Day words: `innaikku`/`இன்னைக்கு` (today), `nethu`/`நேத்து` (yesterday), `munnaal`/`mundhaanethu` (day before yesterday).
- Part of day: `kaalaila` (morning, 09:00), `madhiyam` (noon, 13:00), `saayangaalam` (evening, 18:00), `raathiri`/`night` (21:00), each with precision `part_of_day`.
- Clock: `pathu mani` (10 o'clock), `11 mani`, `3:30`, `moonarai mani` (3:30). AM/PM from part-of-day words, otherwise the latest past time.
- ITN/SMS datetimes pass through.
- The future → `None` + warning. The result is **always read back** as a phrase and confirmed.
- Tests ≥40, with `now` fixed.

### 6.13 `dialog/packet.py` (NEW)
Two renderings of one `Packet`.

**A. Complaint Packet (operator, CFCFRMS field order, copyable text + JSON):**
```
DRAFT — CD-DRAFT-7F3A — not filed. {APP_NAME} is not affiliated with MHA, I4C, NCRP or TN Police.
Status        : ready_for_review | needs_human (reason)
Fraud type    : OTP / bank impersonation
Victim bank   : SBI  (a/c last 4: 1234)      Payment mode: UPI
Called bank?  : No
Txn 1         : ₹40,000  | 02-11-2026 ~15:05 [voice ✓] | UTR 4306 1982 7418 [sms]
Txn 2         : ₹10,000  | 02-11-2026 ~15:09 [voice ✓] | UTR ⚠ verify
Total         : ₹50,000 (2 transactions)
Suspect phone : 98765 43218  [voice ✓ corrected 1×]
Suspect UPI   : —            Suspect bank: —
District      : Madurai
Victim        : — / —
Handled by AI in 2 min 41 s · last debit ~14 min before call end
```
**B. Victim Summary (caller screen + spoken):** draft reference ID, number of transactions, total, and the NEXT_STEPS list. Copy/Share buttons.

Fields with `status="unconfirmed"` → `⚠ verify` and highlighted in the operator UI. Forbidden PII never appears.

### 6.14 NEXT_STEPS (in `dialog/prompts.py`)
Keyed prompts in ta + en, spoken in order, max 5:
1. `NS_CALL_BANK`: call your bank's helpline now, report fraud, ask to block card/UPI.
2. `NS_KEEP_EVIDENCE`: don't delete SMS, call logs or chats; take screenshots.
3. `NS_CHANGE_PIN`: change net-banking/UPI PIN from your own phone.
4. `NS_RECOVERY_SCAM`: anyone offering to "recover" money for a fee is another scam.

Every line needs an official source in `docs/NEXT_STEPS_SOURCES.md` before submission. Until a line has one, show it with a "draft guidance" tag in DEMO_MODE.

### 6.15 `queue/priority.py` + `queue/store.py` (NEW)
- Two lists: **Handoffs** (`needs_human`: wellbeing first, then FIFO) and **Review** (`ready_for_review`).
- **Review order:**
  1. Items waiting > `QUEUE_MAX_WAIT_S` first (FIFO among them).
  2. Then by **confirmed `last_debit_time`, freshest first** (most freezable).
  3. Items with no confirmed time go in arrival order after the ones with times.
  - **The amount is never a sort key.**
- Every position change → an audit log entry `{packet_id, from, to, reason}` (masked), visible in the operator UI.
- Status transitions: `ready_for_review → approved | rejected`; `needs_human → claimed → approved | rejected`. An edit sets `source="operator"` on that field. Store `approval_latency_s` (opened → approved).
- **Approve changes status only.** No network calls, no submission.

### 6.16 Twilio telephony (EXPERIMENTAL)

Lets someone dial a real number and talk to the AI. `TWILIO_ENABLED=false` by default. The app must work fully with it off, and `app/api/routes_twilio.py` is mounted in `main.py` only when it is true.

- **Scope:** `app/twilio_bridge.py` converts between Twilio's 8 kHz µ-law and our 16 kHz pipeline: inbound µ-law → 16 kHz mono WAV for Prisma; Timbre audio → 8 kHz µ-law (`container: "mulaw"`, §2.3) for playback. **Everything else stays the same:** each phone call is one `Session`, with the same FSM, packet flow, queue and operator review.
- **Transport:** Twilio Media Streams, so audio arrives live and stays in memory. Do **not** use `<Record>` (Twilio stores the recording, which breaks §1.3) or `<Gather input="speech">` (Twilio's recogniser replaces Prisma, which breaks the digit pipeline).
- **Routes:** `POST /api/twilio/voice` answers with TwiML, and the WebSocket `/api/twilio/stream` carries the stream. Reject any webhook whose Twilio signature fails validation (Twilio's SDK validator). Twilio's docs do not say the stream handshake is signed, so the signed webhook issues a one-time token, bound to the CallSid, which the stream must present before a session exists.
- **Hang-up:** a caller who hangs up after saying anything still gets a `needs_human` packet with reason `caller_hung_up`.
- **No screen on a phone:** the DTMF keypad replaces ✓/✗ and the numpad, and is authoritative like the buttons: **1 = yes, 2 = no, 3 = repeat, 0 = human**. To type a number, `*` starts entry on a numeric field and `#` submits; while a correction is being asked, keys are digits straight away. A key interrupts the AI. SMS paste is not available, so UTR and amount go through voice read-back or the keypad.
- **Turns:** there is no push-to-talk, so an energy endpointer ends a turn after 1.2 s of quiet. The call is half duplex: the caller is heard only when the AI has finished speaking.
- **Consent and honesty:** the opening is spoken and includes the "experimental" notice and the keys. The phone path sends no SMS and says so at the end.
- **Privacy:** every §1 rule applies. The caller's number (`From`) is masked in logs and is not stored in the packet unless the caller gives it as a field. Test calls still use fake details only.
- **Label:** shown as "experimental telephony" in the demo, the operator UI and the README. Handoff remains a simulated transfer.
- **Tests:** Twilio mocked, signature rejection, the µ-law ↔ 16 kHz round trip, one scripted call reaching the queue, and the routes absent when disabled.

---

## 7. HTTP API

**Caller (`routes_caller.py`)**

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/health` | — | `{ok, gnani_key_present, evon_mode}` |
| POST | `/api/session` | `{lang, consent: true}` | `{session_id, state, prompt, demo_banner}` |
| POST | `/api/session/{id}/turn` | multipart `audio` ≤`MAX_TURN_S` | `TurnResponse` |
| POST | `/api/session/{id}/sms` | `{text}` | `TurnResponse` |
| POST | `/api/session/{id}/confirm` | `{field, txn_index, chunk_index, answer}` | `TurnResponse` |
| POST | `/api/session/{id}/numpad` | `{field, txn_index, digits}` | `TurnResponse` |
| POST | `/api/session/{id}/skip` | `{field, txn_index}` | `TurnResponse` |
| POST | `/api/session/{id}/back` | — | `TurnResponse` (undoes the last answer) |
| POST | `/api/session/{id}/human` | — | `TurnResponse` (forces HANDOFF_HUMAN) |
| GET | `/api/session/{id}/summary` | — | Victim Summary |
| DELETE | `/api/session/{id}` | — | 204 |
| GET | `/api/audio/{hash}.wav` | — | TTS audio |

**Operator (`routes_operator.py`, header `X-Operator-Token`)**

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/operator/queue` | — | `{handoffs[], review[], audit[]}` |
| GET | `/api/operator/packet/{pid}` | — | packet JSON + text + masked transcript (handoffs only) |
| POST | `/api/operator/packet/{pid}/claim` | — | packet (`claimed`) |
| POST | `/api/operator/packet/{pid}/edit` | `{field, txn_index?, value}` | packet (validated) |
| POST | `/api/operator/packet/{pid}/approve` | — | packet (`approved`, `approval_latency_s`) |
| POST | `/api/operator/packet/{pid}/reject` | `{reason}` | packet |
| GET | `/api/events` | — | SSE: `packet_created`, `packet_updated`, `queue_reordered`, `live_fields` |
| GET | `/api/metrics` | — | containment, handoffs by reason, median AHT, median approval time, Gnani p50/p95, cache hit rate (no PII) |

`TurnResponse`:
```json
{
  "state": "READBACK",
  "transcript": "…",
  "txns": [{"index": 0, "amount": {"value": 40000, "display": "₹40,000", "status": "confirmed", "source": "both"},
            "datetime": {...}, "utr": {...}}],
  "fields": {"suspect_phone": {...}, "victim_bank": {...}},
  "readback": {"field": "utr", "txn_index": 0, "chunk_index": 1, "chunk_display": "1982", "total_chunks": 3},
  "prompt": {"text": "…", "audio_url": "/api/audio/ab12….wav"},
  "handoff": null,
  "elapsed_s": 64.2
}
```
- `/turn` pipeline: size/duration check → normalise → STT → safety → FSM → TTS → SSE `live_fields` (so the operator screen fills live) → response.
- Rate limits: `DAILY_SESSION_CAP`, `PER_IP_SESSIONS_PER_HOUR`, `MAX_TURNS_PER_CALL`. A 429 comes with a friendly prompt + "Call 1930".

---

## 8. FRONTEND — KEEP IT SIMPLE (two files, vanilla JS, no build)

**`static/caller.html`** (a phone call screen):
- Premium SaaS look shared with the operator page: dark purple/navy gradient (`#0D0B1A` → `#1A1333`), glass cards (16px radius), purple-to-blue gradient buttons (`#7C3AED` → `#3B82F6`, 12px radius), soft glows, 0.2s transitions, brand-coloured spinners, no animation for reduced motion. Inter when installed, otherwise system fonts: the CSP blocks external fonts.
- Light and dark themes on both pages, dark by default. A sun/moon button in the nav toggles `data-theme` on `<html>` with a 0.3s transition, and the choice is kept in `localStorage`. All colours are CSS variables: `:root` is light, `[data-theme="dark"]` is dark.
- One centred phone-width column. Before the call: a dialler showing **1930** ("Cyber Crime Helpline"), language (Tamil/English), a short consent card and a green round call button.
- In the call: the callee (1930, Cyber Crime Helpline · AI), the call timer and status (Speaking / Listening / Muted / On hold), live captions (the newest AI line highlighted), a display above the keypad, a plain 12-key phone keypad (digits only, no yes/no labels: the opening explains the keys), and Mute, a red End call button and Repeat.
- Half duplex like the phone path: once the AI finishes speaking the line listens by itself; 1.2 s of quiet after speech ends the turn (2 s during the story). Prompt audio plays at 1.3x. A key press interrupts the AI and the open recording.
- Keys follow §6.16: 1 yes, 2 no, 3 repeat, 0 officer, `*` starts typing a number, `#` submits. A question that needs a number (UTR, mobile numbers, an amount the AI could not get, a correction) opens typing straight away; `*` then starts the number again. The display shows what is typed (with the digit count) or the part of a number being read back.
- End call is hanging up: a call with anything in it still reaches an officer (`needs_human`, `caller_hung_up`). No SMS paste, details table, Back or Skip on this screen (the API still has them).
- After the call: the Victim Summary as "SMS from 1930 · simulated in this demo" (reference, total, next steps) + Copy/Share; the call hangs up by itself after the goodbye; on a handoff, "connecting you to an officer (simulated)" and Tele-MANAS for wellbeing. The footer says it is a demo, not connected to the real 1930 line.

**`static/operator.html`** (laptop):
- Token prompt (kept in a JS variable only, no localStorage).
- Three columns. Left sidebar: **Handoffs** (reason chip, "Take call"), **Review queue** (order + wait time + "why here"), calls in progress, recently decided, with status badges: pending yellow, claimed blue, approved green, rejected red. Centre: metrics and the packet. Right: audit log timeline. Log out clears the token and stops the event stream.
- Packet view: Transaction, Victim and Suspect cards with ✓ / ⚠ chips and inline edit; the packet text below keeps CFCFRMS field order; **Approve** / Reject pinned at the bottom; Copy text / Download JSON.
- Live tile for in-progress calls (fields filling via SSE).
- Metrics tiles: calls handled by AI, handoffs, median handling time, median approval time.

---

## 9. SCRIPTS (run in this order first)

1. `make setup` → venv, requirements, check `ffmpeg -version`.
2. `python scripts/smoke_gnani.py` → 1 STT (v2.5, `ta-IN`, `transcribe`) + 1 TTS. Print the JSON shape and latency, and remind the user to check credit usage. **Stop and report if either fails.**
3. `python scripts/probe_prisma_formats.py --clips 8` with configs A–E:
   - A: v2.5 `verbatim`
   - B: v2.5 `transcribe`
   - C: v3.0 `ta-IN,en-IN` `transcribe` + topic/keyterms
   - D: v3.0 `codemix`
   - E: v3.0 `transliterate`

   Include ≥2 clips with time phrases and ≥2 with two transactions. Write `bench/probe/probe_report.md` with exact match on amount/phone/UTR/time and the output script, then **record the STT config decision in `docs/API_NOTES.md`**. Print the call count (40) and ask before running.
4. `python scripts/prerender_prompts.py`.

---

## 10. BENCHMARK (`bench/`)

- **Corpus:** 8 call scripts (OTP/bank KYC with 2 debits, UPI collect, digital arrest with 3 debits, investment, job/task, loan app, fake customer care, sextortion → handoff) × 3–4 speakers, emotional delivery. Each call = a narrative clip + per-slot answer clips + yes/no/correction clips. At least 1 script per speaker is **improvised (unscripted role-play)** with fake numbers from a card. Ground truth is in `manifest.jsonl`.
- Prefer more speakers over more conditions.
- `augment.py` conditions: `clean`, `snr10`, `snr5`, `tel8k` (300–3400 Hz, 8 kHz round-trip, optional µ-law), `snr10_tel8k`.
- **`run_benchmark.py` (field level):** per-field exact match **before read-back**, by condition and field, with n + Wilson 95% CI; the ITN-vs-literal agreement rate and accuracy when they agree vs disagree (**headline engineering result**); `method` breakdown; time-phrase accuracy (within precision); STT p50/p95; cache hit rate; total calls.
- **`simulate_calls.py` (call level, labelled SIMULATION):** feed each call's clips through the real FSM (cached STT), with an oracle answering ✓/✗ against the truth. Report:
  - **Containment rate** (% of calls ending `ready_for_review` with no human)
  - handoffs by reason
  - expected handoffs caught (sextortion must hand off: precision/recall on intended handoffs)
  - corrections per field, fields left unconfirmed
  - **wrong digits that reached the packet as "confirmed"** (must be 0 by design; report it anyway)
  - simulated handling time (sum of clip durations + STT latency + TTS durations)

  Never report a "post-readback accuracy %".
- `report.py` → `bench/RESULTS.md`; the README embeds it verbatim. No hand-edited numbers.

---

## 11. TESTING + QUALITY BAR

- `pytest -q` green, ≥85% coverage on `app/nlp`, `app/dialog`, `app/queue`.
- All Gnani calls mocked (`respx`): 429→200, 504→200, 401, empty transcript, `truncated: true`.
- `ruff check` clean; type hints; `mypy app/nlp app/dialog app/queue` clean.
- `test_state_machine.py` cases:
  - happy path, 1 transaction
  - **3 transactions** (two via voice, one via SMS)
  - correction "illa kadaisi ettu"
  - two failed repairs → unconfirmed
  - silence ×2 → HANDOFF_HUMAN with partial packet
  - "aal venum" mid-call → warm handoff carries all confirmed fields
  - OTP spoken → dropped
  - sextortion → HANDOFF_NONFIN
  - self-harm → HANDOFF_WELLBEING
  - duplicate UTR detected
- `test_priority.py`:
  - the amount never changes order (property test: shuffle amounts, same order)
  - overdue jumps to the top
  - unconfirmed time sorts after confirmed
  - every reorder is audited
- `test_api.py`: the operator token is required; approve without claim on a handoff → 409; SSE emits `live_fields` during a turn; approve makes no outbound network call (assert with respx).

---

## 12. BUILD ORDER (priority, deadline 10 Nov)

1. Skeleton, config, `gnani/http.py`, `stt.py`, `tts.py`, cache, smoke + probe. **Exit:** both APIs return; probe report written; STT config decided.
2. `lexicon_ta.py` + `numbers.py` + `timeparse.py` + tests, built against REAL probe output. `augment.py`. Transcribe the corpus once (cached).
3. `sms_parser.py` (multi-SMS), `validators.py`, `extractor.py`. Baseline `run_benchmark.py`.
4. `state_machine.py` (multi-txn loop + handoffs), `readback.py`, `yesno.py`, `safety.py`, `packet.py`, caller routes. One full call works via tests.
5. `queue/`, operator routes, SSE, `/api/metrics`.
6. `caller.html`, `operator.html`. Two devices on one hosted URL.
7. Full benchmark + `simulate_calls.py`; fix the top 3 failure classes. **FEATURE FREEZE.** Optional Evon only if a GPU endpoint answers in ≤3 s.
8. Deploy (Dockerfile with ffmpeg). README with `RESULTS.md`, `ARCHITECTURE.md`, `NEXT_STEPS_SOURCES.md`, and the exact Gnani model strings used.

**Cut, do not build:** browser automation of any portal, a portal replica, a database, login/OTP flows, evidence upload, non-financial intake, ranking by amount, cross-complaint suspect matching.

**Built alongside the benchmark:** experimental Twilio telephony (§6.16).

---

## 13. DEFINITION OF DONE

- [ ] A Tamil caller on a phone completes a call (one transaction by default; 2 with `MAX_TXNS=2`). The packet appears in the operator queue **with no operator action** until Approve.
- [ ] Operator fields fill **live** (SSE) while the caller speaks.
- [ ] "Aal venum" mid-call → the handoff appears with transcript + already-confirmed fields; the caller is not asked again.
- [ ] Suspect-phone read-back with a voice correction works on camera.
- [ ] SMS paste fills UTR/amount/time with zero API calls.
- [ ] Every number in a packet came from `numbers.py`/`timeparse.py`/`sms_parser.py`/numpad/operator, provable via `source`.
- [ ] Queue order is provably amount-independent (test) and every reorder is audited.
- [ ] Approve makes no outbound call.
- [ ] No raw PII in logs (`grep -E '[6-9][0-9]{9}' logs/*` → nothing).
- [ ] `bench/RESULTS.md` is generated from real runs: field accuracy with n + CI incl. telephone band, plus SIMULATION containment and handling time.
- [ ] Every NEXT_STEPS line has an official source or a visible "draft guidance" tag.
- [ ] The README states limitations honestly: acted corpus, simulated handoff, telephony experimental and off by default, no NCRP integration, Evon status.
- [ ] Works with `EVON_MODE=off`.

---

## 14. HOW TO WORK

- Before coding a Gnani endpoint, open its doc page and confirm the params.
- After each module: run its tests, then commit with a clear message.
- If any assumption here turns out false (e.g. Prisma ITN doesn't convert Tamil number words), STOP, write it to `docs/API_NOTES.md`, propose the adjusted design, then continue.
- Ask before: spending >50 API calls in one script run, adding any paid service, changing the field list, or changing the queue ordering rule.

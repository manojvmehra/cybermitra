# CyberDesk — Claude Code Build Prompt (Backend-first)

> Paste this whole file into Claude Code at the repo root (or save it as `CLAUDE.md`).
> Frontend stays a single static HTML page. All effort goes into the backend, Gnani integration, number pipeline, state machine, and benchmark.

---

## 0. ROLE AND GOAL

You are building **CyberDesk**, a voice-first cyber-fraud complaint *preparation* tool for Tamil Nadu, for the Gnani AI "Great Indian AI Internship Challenge 2026" (deadline **10 Nov 2026, 23:59 IST**).

A victim speaks Tamil / Tanglish / English. The backend transcribes with **Gnani Prisma**, extracts the fields 1930 operators ask for, converts every number **deterministically in code**, reads numbers back in chunks with **Gnani Timbre**, lets the user correct them, and outputs a **1930 Call Card** (text).

It does NOT file complaints, does NOT contact police/banks, does NOT freeze money.

**Core rule of the whole system:** *A language model never decides a digit. Code converts digits. A human confirms digits.*

---

## 1. HARD CONSTRAINTS (NON-NEGOTIABLE)

1. **Synthetic data only.** Challenge rules forbid real phone numbers, account numbers, Aadhaar, PAN or recorded real calls. All test audio is acted by consenting team members. All fixture numbers are obviously fake.
2. **No secrets in git.** `GNANI_API_KEY` only via `.env` (add `.env` to `.gitignore`, ship `.env.example`).
3. **Never store audio to disk in the live app.** Audio lives in memory for the request only. (Benchmark corpus files are separate, under `bench/`, and are acted.)
4. **Never log raw PII.** Mask phone/UTR/amount in every log line (`98•••••210`, `4306••••7418`).
5. **Never ask for OTP, PIN, CVV, password, full account number, Aadhaar, PAN.** If the user speaks one, drop it and do not echo it back.
6. **Never fabricate benchmark numbers.** All reported metrics are computed by `bench/run_benchmark.py` from real API output. No target tables in README.
7. **Async + bounded concurrency.** Gnani may return `429 RATE_LIMITED` ("Only 1 active request is allowed at a time"). Wrap every Gnani call in a global `asyncio.Semaphore(GNANI_MAX_CONCURRENCY)` (default 1) with exponential backoff + jitter (max 4 tries).
8. **Cache every Gnani call** by SHA-256 of (audio bytes or text) + all request params. Cache hits must never hit the network.
9. App name is a config value (`APP_NAME`, default `CyberDesk`). Never hardcode it in prompts/strings — the name may change.

---

## 2. VERIFIED GNANI API FACTS (from docs.gnani.ai, last verified Aug 2026)

**First action:** fetch `https://docs.gnani.ai/llms.txt` and re-verify everything below. If anything differs, the docs win — update `gnani/` clients and note the change in `docs/API_NOTES.md`.

### 2.1 Common
- Base URL: `https://api.vachana.ai`
- Auth header: `X-API-Key-ID: <key>` (optional `X-API-Request-ID` for tracing — use the session id + turn number).
- Python SDK exists: `pip install gnani-vachana` (`from gnani.stt import GnaniSTTClient`, `from gnani.tts import GnaniTTSClient`). **Use raw `httpx` instead** so you control caching, retries, and params. SDK is optional for the smoke test only.
- Gateway errors (401/402/403/429) use `{"detail": {"error_code": ..., "message": ..., "status_code": ...}}`. Endpoint errors use `{"success": false, "error": {"type": ..., "message": ...}}`. 422 uses `{"detail": [...]}`. Parse all three shapes.

### 2.2 STT — Gnani Prisma (REST)
- `POST /stt/v3`, `multipart/form-data`
- Fields:
  - `audio_file` (required) — WAV/MP3/OGG/FLAC/AAC/M4A, **max 30 s**. Server resamples to 16 kHz mono.
  - `language_code` (required) — Tamil = `ta-IN`, English = `en-IN`.
  - `model` — omit → **Prisma v2.5** (response `model: "gnani-prisma-v2.5"`). `prisma-v3.0` → Prisma v3.0.
  - `format` — `verbatim` (default) | `transcribe` (ITN: numbers/currency/phone → digits) | v3.0 only: `codemix`, `transliterate` (whole transcript in Latin letters, numbers spelled as words).
  - v2.5: `bias_list` (≤100 single letter-only words) + `bias_score` ∈ {0, 0.5, 1.0, 1.5, 2.0}.
  - v3.0: `language_code` may be `indic-auto` or comma list ≤4 (e.g. `ta-IN,en-IN`); `keyterms` (JSON array ≤200), `topic` (≤1600 chars), `previous_text` (last 600 chars kept).
  - `enable_substitution` + `substitution_map` (≤10 rules) on both.
- Response (v2.5): `{success, request_id, transcript, model, processing_time, end_to_end_latency, output: {literal}}`
  → **`output.literal` is the pre-ITN transcript.** With `format=transcribe` one call gives BOTH the ITN digits (`transcript`) and the spoken words (`output.literal`). Use this.
- Response (v3.0): adds `detected_language_code`; may include `truncated: true` (retry with shorter audio). No `output.literal`.
- Empty transcript `""` is not an error (silence / <0.1 s).
- v3.0 can return `504` with body `{"error","code":"UPSTREAM_TIMEOUT","message"}` → retry once.
- Realtime WebSocket and Batch STT exist (`/api/STT/stt-websocket`, `/api/STTBatch/Introduction`) — **not needed for MVP**; push-to-talk + REST is the design.

### 2.3 TTS — Gnani Timbre (REST)
- `POST /api/v1/tts/inference`, JSON body:
```json
{ "text": "...", "voice": "<from catalog>", "model": "timbre-v2.5",
  "language": "ta-IN", "speed": 0.9,
  "audio_config": {"sample_rate": 24000, "num_channels": 1, "sample_width": 2,
                   "encoding": "linear_pcm", "container": "wav"} }
```
- Returns raw audio bytes. **Timbre v2.0 is deprecated → use `timbre-v2.5`** (v3.0 also exists with audio tags; keep it as a config option).
- Voices are per-model. **Do not guess voice names** — fetch the catalog page (`/api/TTS/available-voices`) and pick a Tamil-preferred voice for v2.5; store in `TTS_VOICE_TA` / `TTS_VOICE_EN`.
- `speed` range 0.85–1.15. Use **0.9** for read-backs.
- Timbre's text normalisation groups 10-digit phones 3-3-4 and may compress repeated digits ("double four"). **For read-back we must control chunking ourselves** → we send digits as explicit Tamil/English digit WORDS separated by commas (see §6.5), not raw digit strings.
- Telephony output (`container: mulaw`, 8 kHz) is available if a phone path is ever added.

### 2.4 LLM — Gnani Evon v3.3 (OPTIONAL)
- **Not on the Gnani API platform.** Open weights on Hugging Face: `gnani/gnani-evon-v3.3-30B-A3B` (also listed as `gnani/gnani-evon-v3.3`). Hybrid Mamba MoE, ~31.7B params, BF16, 128K ctx, Apache-2.0. Model card targets vLLM ≥ 0.12 on A100/H100 80GB. Q4 GGUF ≈ 21 GB VRAM (third-party estimate).
- Serve with vLLM → OpenAI-compatible `/v1/chat/completions`. Disable reasoning: `"chat_template_kwargs": {"enable_thinking": false}`.
- Design: `EVON_MODE=off|openai_compat` (default **off**). The app must be fully functional with Evon off. Evon is an *enhancer* for narrative slot attribution and fraud-type classification, never for digits.

### 2.5 Challenge rule facts that affect design
- Must name every Gnani model used in the submission. Prisma + Timbre alone satisfy "at least one Gnani model". Evon is a bonus if it runs.
- One award max per team. Primary target: **Mixed Vibes (best code-mixed voice build)**. "Noise Canceller" is judged on noisy *telephone* audio → the benchmark must include 8 kHz telephone-band conditions.
- Honest limitations are preferred over faked demos.

---

## 3. ARCHITECTURE

```
Browser (static HTML, push-to-talk, ≤25 s clips, paste-SMS box, ✓/✗ buttons, numpad)
   │  multipart audio (webm/ogg/mp4)          JSON
   ▼
FastAPI (app/main.py)
   ├── audio.normalize()  → ffmpeg → 16 kHz mono WAV  (browser webm is NOT accepted by Prisma)
   ├── gnani.stt.transcribe()  ──► Prisma (REST, cached, semaphore, retry)
   ├── nlp.numbers  (Tamil script + romanised Tanglish + English + digits → int / digit string)
   ├── nlp.sms_parser (bank SMS → UTR, amount, bank, datetime, VPA)  ← exact, zero credits
   ├── nlp.extractor  (rules default; Evon optional) → candidate fields + provenance
   ├── nlp.validators (phone, UTR, UPI, amount bounds, datetime)
   ├── nlp.yesno      (Tamil/Tanglish/English yes/no/correction intents)
   ├── dialog.state_machine (per-session FSM)
   ├── dialog.readback (chunking + Tamil/English digit words for TTS)
   ├── gnani.tts.synthesize() ──► Timbre (REST, cached; static prompts pre-rendered)
   └── card.render() → plain-text 1930 Call Card
Session store: in-memory dict, TTL 30 min, no DB.
```

**Key design decisions (implement exactly):**
1. **Slot is known from the question.** In GAP_FILL the system asks for ONE field at a time, so the answer's slot is the asked slot. Narrative extraction (first free-form turn) is best-effort; gap-fill is deterministic.
2. **Dual-channel number reading on Prisma v2.5:** one call with `format=transcribe` → `transcript` (ITN digits) + `output.literal` (spoken words). Parse BOTH independently. If they agree → `confidence=high`. If they disagree or only one parses → `confidence=low`. Both cases go to read-back; low confidence reads back the literal-parse and offers numpad first.
3. **Paste-first for UTR/amount/time.** If the user pastes a bank SMS, values from SMS get `source="sms"`, are shown on screen, and are NOT re-confirmed by voice (still editable). Voice read-back is for spoken values (especially the suspect phone number, which the victim only heard).
4. **Buttons beat voice for confirmation.** Every read-back chunk can be confirmed by a ✓/✗ button OR by voice. Button input is authoritative.
5. **Any "no" wins.** Ambiguous voice → treat as "no" and re-ask that chunk.
6. **Max 2 repair attempts per field**, then mark `status="unconfirmed"` and move on; the card shows it with "⚠ verify".

---

## 4. REPO LAYOUT (create exactly this)

```
cyberdesk/
├── CLAUDE.md                      # this prompt
├── README.md                      # setup, run, architecture, HONEST measured benchmark table
├── .env.example
├── pyproject.toml                 # python 3.11, ruff, pytest config
├── requirements.txt
├── Makefile                       # setup, run, test, probe, prerender, bench, lint
├── app/
│   ├── main.py                    # FastAPI app factory, routes mount, static mount
│   ├── config.py                  # pydantic-settings Settings
│   ├── logging_utils.py           # structured JSON logs + mask()
│   ├── audio.py                   # ffmpeg normalize, duration check, split >25 s
│   ├── cache.py                   # SHA-256 disk cache (JSON for STT, WAV for TTS)
│   ├── ratelimit.py               # per-IP + per-session limits, daily session cap
│   ├── gnani/
│   │   ├── http.py                # shared httpx.AsyncClient, semaphore, retry, error parsing
│   │   ├── stt.py                 # transcribe(audio_wav, profile) -> SttResult
│   │   ├── tts.py                 # synthesize(text, lang, voice, speed) -> bytes
│   │   └── evon.py                # optional OpenAI-compatible client
│   ├── nlp/
│   │   ├── lexicon_ta.py          # Tamil-script + romanised number words, bank names, cues
│   │   ├── numbers.py             # parse_amount, parse_digit_string, normalise_text
│   │   ├── sms_parser.py
│   │   ├── extractor.py           # rule extractor + Evon merge
│   │   ├── validators.py
│   │   ├── yesno.py
│   │   └── safety.py              # forbidden-PII detection, handoff cues, self-harm cues
│   ├── dialog/
│   │   ├── models.py              # pydantic: Field, Session, Turn, Card
│   │   ├── prompts.py             # all spoken/text prompts, ta + en, keyed IDs
│   │   ├── readback.py            # chunking + digit-word rendering
│   │   └── state_machine.py
│   ├── card.py                    # render 1930 card text
│   └── api/
│       ├── routes_session.py
│       └── schemas.py
├── static/
│   └── index.html                 # ONE file, vanilla JS, no build step
├── scripts/
│   ├── smoke_gnani.py             # 1 STT + 1 TTS call, prints latency + response shape
│   ├── probe_prisma_formats.py    # compares STT configs on sample clips → probe_report.md
│   └── prerender_prompts.py       # renders all static prompts to cache via Timbre
├── bench/
│   ├── corpus/                    # acted clips (gitignored audio; manifest committed)
│   ├── manifest.jsonl             # {clip_id, script_id, speaker, field_truth{...}}
│   ├── noise/                     # recorded street/bus noise (gitignored)
│   ├── augment.py                 # clean, snr10, snr5, tel8k, snr10+tel8k
│   ├── run_benchmark.py
│   └── report.py                  # markdown tables with n + Wilson 95% CI
├── tests/
│   ├── test_numbers_ta.py         # ≥120 cases
│   ├── test_sms_parser.py         # ≥25 SMS formats (synthetic)
│   ├── test_validators.py
│   ├── test_yesno.py
│   ├── test_readback.py
│   ├── test_state_machine.py      # scripted dialogs with mocked STT
│   └── test_api.py                # httpx TestClient, Gnani mocked
└── docs/
    ├── API_NOTES.md               # any doc deviations found
    └── ARCHITECTURE.md
```

---

## 5. CONFIG (`app/config.py`, pydantic-settings)

```
GNANI_API_KEY=                 # required
GNANI_BASE_URL=https://api.vachana.ai
GNANI_MAX_CONCURRENCY=1
GNANI_TIMEOUT_S=30

STT_MODEL=v2.5                 # v2.5 | v3.0   (decided by probe; default v2.5 for output.literal)
STT_LANGUAGE=ta-IN             # v3.0 may use "ta-IN,en-IN"
STT_FORMAT=transcribe          # transcribe | verbatim | codemix | transliterate
STT_BIAS_SCORE=1.0             # v2.5 only
STT_V3_TOPIC=Cyber fraud complaint: bank, UPI, amount, phone number, transaction ID

TTS_MODEL=timbre-v2.5
TTS_VOICE_TA=                  # fill from voice catalog
TTS_VOICE_EN=                  # fill from voice catalog
TTS_SPEED_PROMPT=1.0
TTS_SPEED_READBACK=0.9
TTS_SAMPLE_RATE=24000

EVON_MODE=off                  # off | openai_compat
EVON_BASE_URL=http://localhost:8000/v1
EVON_MODEL=model
EVON_TIMEOUT_S=8

APP_NAME=CyberDesk
SESSION_TTL_S=1800
MAX_CLIP_S=25
DAILY_SESSION_CAP=40
PER_IP_SESSIONS_PER_HOUR=6
CACHE_DIR=.cache
DEMO_MODE=true                 # shows "demo only — do not enter real details" banner
```

---

## 6. MODULE SPECS

### 6.1 `gnani/http.py`
- One module-level `httpx.AsyncClient(timeout=GNANI_TIMEOUT_S)`.
- `async def call(method, path, *, files=None, data=None, json=None, expect="json"|"bytes", request_id)`.
- Semaphore around the network call. Retry on 429, 500, 503, 504, `httpx.TransportError`: backoff `0.5 * 2**n + rand(0, 0.3)`, max 4 attempts. No retry on 400/401/402/403/422.
- Raise `GnaniError(status, code, message, request_id)`; normalise the three error shapes.
- Record per-call metrics into an in-memory counter (`calls_by_endpoint`, `cache_hits`, `latency_ms` list) exposed at `GET /api/metrics` (no PII).

### 6.2 `gnani/stt.py`
```python
@dataclass
class SttResult:
    text: str              # transcript (ITN'd if format=transcribe)
    literal: str | None    # v2.5 output.literal
    model: str
    detected_language: str | None
    truncated: bool
    latency_ms: int
    cached: bool
```
- `async def transcribe(wav_bytes: bytes, *, profile: SttProfile, bias_words: list[str] | None, context: str | None) -> SttResult`
- `SttProfile` built from config; v2.5 path omits `model`, sends `bias_list` (JSON array) + `bias_score`; v3.0 path sends `model=prisma-v3.0`, `keyterms`, `topic`, `previous_text` (= last assistant prompt text, ≤600 chars).
- Cache key = sha256(wav_bytes) + sorted params JSON.
- `bias_list` default (letters only, single words): `["SBI","HDFC","ICICI","Axis","Canara","Indian","IOB","Kotak","PhonePe","GPay","Paytm","UPI","UTR","OTP","KYC","IMPS","NEFT"]` plus Tamil-script equivalents from `lexicon_ta.BANK_ALIASES`. Validate letters-only before sending (invalid list is silently ignored by API — log a warning if you had to drop entries).

### 6.3 `gnani/tts.py`
- `async def synthesize(text, *, lang: Literal["ta-IN","en-IN"], speed: float) -> bytes` (WAV).
- Cache key = sha256(text + voice + model + lang + speed + sample_rate). Store WAV under `CACHE_DIR/tts/<hash>.wav`; return a URL `/api/audio/<hash>.wav`.
- `scripts/prerender_prompts.py` renders every static prompt in `dialog/prompts.py` for both languages at startup-time-zero cost.

### 6.4 `nlp/numbers.py` + `nlp/lexicon_ta.py` (THE CORE — test hardest)

Input can arrive in four shapes; handle all:
1. **ITN digits**: `₹50,000`, `50000`, `9876543210`, `5,20,000`.
2. **Tamil script words** (Prisma v2.5 literal / verbatim): `ஐம்பதாயிரம்`, `ஒன்றரை லட்சம்`, `ஒன்பது எட்டு ஏழு…`.
3. **Romanised Tanglish** (Prisma v3.0 `transliterate`, or manual input): `aimbadhaayiram`, `onnara latcham`, `rendu latchathi irubathanju aayiram`.
4. **English words / shorthand**: `fifty thousand`, `50k`, `1.5 lakh`, `one and a half lakh`, `double nine triple eight`.

Public API:
```python
def normalise_text(s: str) -> str        # NFC, strip punctuation except ₹ , . @, collapse spaces, lowercase Latin
def parse_amount(s: str) -> ParseResult  # value: int rupees | None, spans, method, warnings
def parse_digit_string(s: str, expected_len: int | None) -> ParseResult  # value: str of digits
def find_number_spans(transcript: str) -> list[Span]   # deterministic scanner, no LLM
```

Lexicon to implement in `lexicon_ta.py` (Tamil script + common romanisations + colloquial forms). **Karthikeyan (native speaker) must review every entry and add variants Prisma actually emits (see probe report).**

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
| 1000 | ஆயிரம் (combining: ஆயிரத்து) | aayiram, ayiram, aayirathu |
| 1e5 | லட்சம், லட்சத்து, லட்சத்தி | latcham, lakh, latchathu, latchathi |
| 1e7 | கோடி | kodi, crore |
| ½ | அரை (ஒன்றரை = 1.5, ரெண்டரை = 2.5) | arai, onnara, rendara |
| ¼, ¾ | கால், முக்கால் | kaal, mukkaal |

Rules:
- **Sandhi splitting:** `ஐம்பதாயிரம்` = ஐம்பது+ஆயிரம்; `இருபத்தைந்து` = 25; `இருபத்தி ஐந்து` = 25; `நூற்றி ஐம்பது` = 150. Implement a greedy longest-match tokenizer over a stem table, not regex soup.
- **Combining forms** (`-த்து`, `-த்தி`, `-ற்றி`) mean "and continue".
- **Multiplier stack:** standard Indian grammar `(a × 1e7) + (b × 1e5) + (c × 1000) + (d × 100) + e`.
- **Fractions** only valid before a multiplier (`ஒன்றரை லட்சம்` → 150000).
- **"k"** = ×1000; `1.5 lakh` → 150000; `₹` and `rupees`/`ரூபாய்`/`rubaa` are unit markers, not digits.
- **Digit strings**: sequence of single-digit words or digits; expand `double X` / `டபுள் X` / `triple X`; ignore fillers (`uh`, `அ`, `ம்`, `ok`). Never merge two different spoken numbers separated by a filler longer than ~1 token gap — return both spans.
- **Ambiguity → warning, not guess.** E.g. `ஐநூறு` vs `ஐம்பது` both plausible from noisy text → return `value=None, warnings=["ambiguous"]` only if the tokenizer genuinely produced two parses.
- Return `method ∈ {"itn_digits","tamil_words","roman_words","english_words","mixed"}` for benchmark slicing.

Tests (`tests/test_numbers_ta.py`) must include at minimum: every row of the table, 30 compound amounts (e.g. 2,25,000 / 1,50,000 / 49,999 / 1,00,500 / 12,34,567), 20 phone digit strings (with double/triple, mixed Tamil+English digits), 20 UTR strings, 15 adversarial (fillers, repeated words, `rendu moonu` meaning "a couple" in non-number context → no amount), and round-trip `render_digits_ta(parse(x)) == x`.

### 6.5 `dialog/readback.py`
- Phone: 5+5 chunks. UTR: 4+4+4. UPI ID: local part chunked by 4, then "at", then handle letter-by-letter. Amount: read as words + "ரூபாய்" (let Timbre TN read `₹50,000` with `language="ta-IN"`), then ALSO show digits on screen.
- `render_digits_ta(chunk: str) -> str`: map each digit to the Tamil digit word, join with `", "` (comma = pause) so Timbre reads one digit at a time and cannot regroup or compress. `render_digits_en` same for English.
- Read-back prompt template (ta): `"{field_label}: {chunk_words}. சரியா?"`; (en): `"{field_label}: {chunk_words}. Is that right?"`
- Return `ReadbackStep{field, chunk_index, chunk_digits, text, audio_url}`.

### 6.6 `nlp/sms_parser.py`
Parse pasted bank/UPI SMS (synthetic fixtures only). Extract with named regex patterns + bank keyword table:
- UTR/RRN/Ref: 12-digit run near `UTR|RRN|Ref|Ref No|UPI Ref|Txn ID` (case-insensitive); also IMPS 12-digit.
- Amount: `(?:Rs\.?|INR|₹)\s?([\d,]+(?:\.\d{1,2})?)` near `debited|sent|paid|transferred`.
- Bank: from sender/keywords (SBI, HDFC, ICICI, Axis, Canara, Indian Bank, IOB, Kotak, BoB, PNB, Union, …).
- Datetime: `dd-mm-yy`, `dd/mm/yyyy`, `ddMonyy`, `HH:MM(:SS)?`, with IST assumption.
- Beneficiary VPA: `[\w.\-]{2,}@[a-z]{2,}`.
- Return each field with `source="sms"`, `confidence="high"`, and `raw_span`. Never extract or return the victim's own full account number; if `A/c XX1234` appears, keep only last 4 as `victim_account_last4`.

### 6.7 `nlp/extractor.py`
- `extract_narrative(stt: SttResult, lang) -> dict[field, Candidate]` — rules only:
  - Bank: alias table match (Tamil script + Latin) → canonical name.
  - Fraud type: keyword cues → enum `{OTP_BANK_CALL, UPI_COLLECT, DIGITAL_ARREST, INVESTMENT, JOB_TASK, LOAN_APP, FAKE_CUSTOMER_CARE, OTHER}`.
  - Amount: number span within ±6 tokens of cues (`போச்சு/pochu`, `அனுப்பினேன்/anuppinen`, `debit`, `ரூபாய்/rubaa/rupees`, `cut aachu`).
  - Suspect phone: 10-digit span within ±8 tokens of `call vandhuchu/கால் வந்துச்சு/number la irundhu/அந்த நம்பர்`; victim phone only if preceded by `en/என்/ennoda/my`.
  - Datetime: `இன்னைக்கு/innaikku/today`, `நேத்து/nethu/yesterday`, `மணி/mani/o'clock`, ITN times.
- Each `Candidate{value, confidence, source: "voice_itn"|"voice_literal"|"both"|"evon"|"sms"|"numpad", span_text}`.
- **Evon merge (only if `EVON_MODE != off`)**: send transcript + literal, ask for JSON `{bank, fraud_type, slots: {amount_span, suspect_phone_span, victim_phone_span, utr_span}}` where every `*_span` MUST be an exact substring of the input. Post-validate: if a span is not an exact substring → discard. Spans are then parsed by `numbers.py` — Evon's own digits are never used. Timeout `EVON_TIMEOUT_S` → fall back to rules silently. Evon system prompt: temperature 0, `enable_thinking=false`, "Output JSON only. Copy spans verbatim. Never write digits that are not in the input."

### 6.8 `nlp/validators.py`
- Indian mobile: 10 digits, starts 6–9; strip `+91`/`91`/`0` prefix.
- UTR/RRN: exactly 12 digits. 11 or 13 → specific re-ask prompt with the count heard.
- UPI: `^[\w.\-]{2,256}@[a-zA-Z]{2,64}$`.
- Amount: 1 ≤ x ≤ 10,00,00,000; > ₹10 lakh → extra confirmation step.
- Datetime: not in the future; > 7 days ago → warn "freeze less likely, still report".

### 6.9 `nlp/yesno.py`
- Intents: `YES`, `NO`, `CORRECTION(new_digits?, position?)`, `DONT_KNOW`, `REPEAT`, `HUMAN`, `UNKNOWN`.
- YES: ஆமா, ஆமாம், சரி, சரிதான், ஹா, ok, okay, yes, correct, aama, sari, seri, haan.
- NO: இல்ல, இல்லை, தப்பு, வேண்டாம், illa, thappu, no, wrong.
- DONT_KNOW: தெரியல, theriyala, don't know, theriyadhu.
- REPEAT: திரும்ப, thirumba, again, repeat, enna.
- HUMAN: ஆள் வேணும், aal venum, officer, human.
- CORRECTION: NO + digits present ("illa, kadaisi number ettu") → extract digits via `numbers.py`; position words `கடைசி/kadaisi/last`, `முதல்/mudhal/first`. If position unresolvable → replace the whole chunk with the new digits only if the new digit count == chunk length; otherwise ask numpad.
- Ambiguous / both yes and no present → `NO` (any "no" wins).

### 6.10 `nlp/safety.py`
- Forbidden PII detectors: OTP/PIN/CVV/password context words + digit run of 4–6 → drop, respond with prompt `NEVER_SHARE_OTP`.
- Handoff cues: non-financial (sextortion/morphed photo/harassment keywords) → state `HANDOFF_NONFIN` (collect nothing, show 1930 + cybercrime.gov.in).
- Self-harm cues (Tamil + English list) → `HANDOFF_WELLBEING`: stop intake, show Tele-MANAS 14416 and 1930. (Team: re-verify the Tele-MANAS number from an official source before submission.)

### 6.11 `dialog/state_machine.py`
States:
```
CONSENT → OPENING → NARRATIVE → GAP_FILL(field) → READBACK(field, chunk) → REVIEW → CARD
                        ↑______________________________|
Any state → HANDOFF_HUMAN | HANDOFF_NONFIN | HANDOFF_WELLBEING | END
```
- Field order for GAP_FILL (skip if already confirmed or from SMS): `amount → bank → datetime → utr → suspect_phone → suspect_upi(optional) → victim_name → victim_mobile → district`.
  - UTR prompt first offers: "Paste the bank SMS, type it, or say it."
  - `district` is asked because 1930 operators route by location.
- Transitions are pure functions: `next_state(session, event) -> (session, actions)` where events are `AUDIO_TURN(stt)`, `SMS_PASTED(text)`, `BUTTON(field, chunk, yes|no)`, `NUMPAD(field, digits)`, `SKIP(field)`, `TIMEOUT`.
- Counters: `repair_attempts[field]` (max 2), `silence_count` (2 × empty transcript → HANDOFF_HUMAN prompt with 1930).
- `actions` = list of `SpeakPrompt(id|text)`, `ShowReadback(step)`, `UpdateFields`, `ShowCard`.
- 100% unit-testable with no network.

### 6.12 `card.py`
Plain text, ≤ 12 lines, copyable:
```
DRAFT — not filed. {APP_NAME} is not affiliated with MHA, I4C, NCRP or TN Police.
Fraud type : OTP / bank impersonation
Amount     : ₹50,000            [voice ✓]
Bank       : SBI                [voice ✓]
Date/time  : 02-11-2026 ~15:00  [sms]
UTR/Ref    : 4306 1982 7418     [sms]
Suspect ph : 98765 43218        [voice ✓ corrected 1×]
Suspect UPI: —
District   : Madurai
Your name  : —
Your mobile: —
Call 1930 now. Read these lines to the officer. Also file at cybercrime.gov.in
Prepared in 1 min 47 s
```
Fields with `status="unconfirmed"` show `⚠ verify`. Never include anything flagged forbidden PII.

---

## 7. HTTP API (`app/api/routes_session.py`)

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/health` | — | `{ok, gnani_key_present, evon_mode}` |
| POST | `/api/session` | `{lang: "ta"|"en", consent: true}` | `{session_id, state, prompt{text, audio_url}, demo_banner}` |
| POST | `/api/session/{id}/turn` | multipart `audio` (webm/ogg/mp4/wav, ≤25 s) | `TurnResponse` |
| POST | `/api/session/{id}/sms` | `{text}` | `TurnResponse` |
| POST | `/api/session/{id}/confirm` | `{field, chunk_index, answer: "yes"|"no"}` | `TurnResponse` |
| POST | `/api/session/{id}/numpad` | `{field, digits}` | `TurnResponse` |
| POST | `/api/session/{id}/skip` | `{field}` | `TurnResponse` |
| GET | `/api/session/{id}/card` | — | `{text, fields, elapsed_s}` |
| DELETE | `/api/session/{id}` | — | `204` (wipe) |
| GET | `/api/audio/{hash}.wav` | — | cached TTS audio |
| GET | `/api/metrics` | — | call counts, cache hit rate, p50/p95 latency (no PII) |

`TurnResponse`:
```json
{
  "state": "READBACK",
  "transcript": "…",             // shown to user; masked in logs only
  "fields": {"amount": {"value": 50000, "display": "₹50,000", "status": "pending|confirmed|unconfirmed", "source": "both"}},
  "readback": {"field": "suspect_phone", "chunk_index": 1, "chunk_display": "43218", "total_chunks": 2},
  "prompt": {"text": "…", "audio_url": "/api/audio/ab12….wav"},
  "handoff": null,
  "elapsed_s": 64.2
}
```
- `/turn` pipeline: size/duration check → `audio.normalize` (ffmpeg `-ac 1 -ar 16000 -f wav`) → if >25 s reject with prompt to speak shorter → STT → safety → FSM → TTS for dynamic prompt → response.
- Rate limits: `DAILY_SESSION_CAP`, `PER_IP_SESSIONS_PER_HOUR`, max 40 turns/session. Return 429 with a friendly prompt + "Call 1930".

---

## 8. FRONTEND (`static/index.html`) — KEEP IT SIMPLE

One HTML file, vanilla JS, no framework, no build:
- Top, always visible: big red **"Call 1930"** `<a href="tel:1930">` button, and the demo banner when `DEMO_MODE`.
- Consent checkbox + Start (Tamil / English toggle).
- Push-to-talk button (`MediaRecorder`, hard stop at 25 s, upload on release).
- "Paste bank SMS" textarea + submit.
- Live field panel (value + status chip).
- Read-back panel: current chunk in large digits + ✓ and ✗ buttons; numpad modal on ✗ or low confidence.
- Card view with Copy (`navigator.clipboard`) and Share (`navigator.share`, fallback to copy).
- Auto-play `prompt.audio_url`. Footer non-affiliation text.
No localStorage. Session id in a JS variable only.

---

## 9. SCRIPTS (run in this order on Day 1)

1. `make setup` → venv, `pip install -r requirements.txt`, check `ffmpeg -version`.
2. `python scripts/smoke_gnani.py` → 1 STT call on `bench/corpus/smoke.wav` (v2.5, `ta-IN`, `transcribe`) + 1 TTS call. Print full JSON shape, latency, and remind the user to read credit usage on the dashboard. **Stop and report if either fails.**
3. `python scripts/probe_prisma_formats.py --clips 8` → for each clip in `bench/corpus/probe/` run these configs and save raw responses to `bench/probe/*.jsonl`:
   - A: v2.5, `ta-IN`, `verbatim`
   - B: v2.5, `ta-IN`, `transcribe` (gives `transcript` + `output.literal`)
   - C: v3.0, `ta-IN,en-IN`, `transcribe`, with `topic` + `keyterms`
   - D: v3.0, `ta-IN,en-IN`, `codemix`
   - E: v3.0, `transliterate`
   Then run `numbers.py` on each output vs manifest truth and write `bench/probe/probe_report.md`: per config, exact-match on amount / phone / UTR, which script the numbers came out in, and 3 raw examples. **Pick `STT_MODEL/STT_FORMAT` from this report and record the decision in `docs/API_NOTES.md`.** (8 clips × 5 configs = 40 calls — print the count before running and ask for confirmation.)
4. `python scripts/prerender_prompts.py` → all static prompts, both languages.

---

## 10. BENCHMARK (`bench/`)

- Corpus: 8 scripts (OTP/bank KYC, UPI collect, digital arrest, investment, job/task, loan app, fake customer care, sextortion→handoff) × 3–4 speakers, emotional delivery. Each script embeds: amount, suspect phone, UTR (spoken), bank, time. Ground truth in `manifest.jsonl`.
- Prefer **more speakers over more conditions** if time is short.
- `augment.py` conditions: `clean`, `snr10`, `snr5` (mix recorded street noise at target SNR using RMS), `tel8k` (band-pass 300–3400 Hz, resample 8 kHz, back to 16 kHz for upload, optional µ-law round-trip), `snr10_tel8k`.
- `run_benchmark.py`: STT (cached) → extractor → per-field exact match **before read-back**. Report:
  - Field exact-match by condition and by field, with **n and Wilson 95% CI**.
  - Agreement rate between ITN-parse and literal-parse, and accuracy when they agree vs disagree (this is the headline engineering result).
  - Number-format breakdown (`method`).
  - STT latency p50/p95, cache hit rate, total API calls (credit proxy).
- **Read-back simulation is labelled as simulation**: an oracle that answers YES/NO per chunk against truth. Report *corrections needed per field* and *fields still unconfirmed after 2 attempts*, NOT a "post-readback accuracy %" (it would be ~100% by construction).
- `report.py` writes `bench/RESULTS.md`; README embeds it verbatim. No hand-edited numbers.

---

## 11. TESTING + QUALITY BAR

- `pytest -q` green, ≥ 85% coverage on `app/nlp` and `app/dialog`.
- All Gnani calls mocked in tests (`respx`), including 429-then-200, 504-then-200, 401, empty transcript, `truncated: true`.
- `ruff check` clean. Type hints everywhere; `mypy app/nlp app/dialog` clean.
- `tests/test_state_machine.py` covers: happy path voice-only; SMS-paste path; correction "illa kadaisi ettu"; two failed repairs → unconfirmed; silence ×2 → handoff; OTP spoken → dropped; sextortion → HANDOFF_NONFIN; self-harm → HANDOFF_WELLBEING.

---

## 12. BUILD ORDER (match the team's 8-day plan)

1. **Day 1 (Mon 2 Nov):** repo skeleton, config, `gnani/http.py`, `stt.py`, `tts.py`, cache, `smoke_gnani.py`, `probe_prisma_formats.py`. Exit: both APIs return, response shapes logged, credit cost noted, probe report exists.
2. **Day 2:** `lexicon_ta.py` + `numbers.py` + 120 tests, built against REAL probe output. `augment.py`. Transcribe full corpus once (cached).
3. **Day 3:** `sms_parser.py`, `validators.py`, `extractor.py` (rules). First `run_benchmark.py` baseline.
4. **Day 4:** `state_machine.py`, `readback.py`, `yesno.py`, `safety.py`, routes. One full session works via `curl`/tests. Pre-render prompts.
5. **Day 5:** `static/index.html`, numpad, SMS paste, card, rate limits, masked logging, `/api/metrics`.
6. **Day 6:** full benchmark, fix top 3 failure classes, FEATURE FREEZE. Optional: Evon behind flag if a GPU endpoint is available (≤3 s per call or drop it).
7. **Day 7:** deploy (Railway/Render; ensure ffmpeg in image — provide `Dockerfile` with `apt-get install -y ffmpeg`), demo recording support.
8. **Day 8:** README with measured `RESULTS.md`, `docs/ARCHITECTURE.md`, list of Gnani models used with exact model strings (`gnani-prisma-v2.5` / `prisma-v3.0`, `timbre-v2.5`, optional `gnani-evon-v3.3-30B-A3B`).

---

## 13. DEFINITION OF DONE

- [ ] `make run` serves the app; a full Tamil session produces a card in < 3 min using only Prisma + Timbre.
- [ ] SMS paste fills UTR/amount/time with zero API calls.
- [ ] Suspect-phone read-back with a voice correction works on camera.
- [ ] Every number on the card came from `numbers.py`/`sms_parser.py`/numpad — provable via `source` field.
- [ ] No raw PII in logs (`grep -E '[6-9][0-9]{9}' logs/*` returns nothing).
- [ ] `bench/RESULTS.md` generated from real runs with n + CI, includes telephone-band conditions.
- [ ] README states limitations honestly (corpus size, acted audio, Evon status, web-mic vs phone).
- [ ] Works with `EVON_MODE=off`.

---

## 14. HOW TO WORK

- Before writing code for a Gnani endpoint, open its doc page and confirm the params.
- After each module: run its tests, then commit with a clear message.
- If any assumption in this prompt turns out false (e.g. Prisma Tamil ITN does not convert Tamil number words), STOP, write the finding to `docs/API_NOTES.md`, propose the adjusted design, then continue.
- Ask me before: spending > 50 API calls in one script run, adding any paid service, or changing the field list.

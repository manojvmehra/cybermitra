# Gnani API notes and deviations

Verified against `https://docs.gnani.ai/llms.txt` and the linked pages on **2026-11-02**. Where the build
prompt and the docs differ, the docs win and the code follows the docs.

## Deviations from the build prompt

| # | Prompt said | Docs say (2026-11-02) | What the code does |
|---|---|---|---|
| 1 | v2.5 response `model: "gnani-prisma-v2.5"` | `model` is `"prisma-v2.5"` | `SttResult.model` stores whatever the API returns; fallback string is `prisma-v2.5`. |
| 2 | Three error shapes | **Four**: TTS synthesis errors (400/500/503) use a flat `{"success": false, "message", "status_code"}` body | `gnani/http.py::parse_error` handles all four (plus non-JSON). |
| 3 | — | New STT field `itn_native_numerals` (default `false`, only with `format=transcribe`) renders digits in native script | Not sent (we want ASCII digits). `normalise_text` maps Tamil digits ௦–௯ to ASCII anyway. |
| 4 | — | v2.5 `format` accepts only `verbatim` or `transcribe` (`INVALID_FORMAT` otherwise); v2.5 `language_code` accepts a single code | `stt.build_form` raises `ValueError` before spending a call. |
| 5 | Invalid `bias_list` is silently ignored | Confirmed. Invalid `bias_score` is also skipped (non-numeric → 422) | We filter to letter-only single words (Unicode letters + combining marks, so Tamil script survives) and log the number dropped. |
| 6 | — | v3.0 `bias_list` is the old name for `keyterms`, used only when `keyterms` is absent | v3.0 path sends `keyterms` only. |
| 7 | — | Audio < 0.1 s returns `success` + empty `transcript` with **no** `model` or timing fields | Missing fields are tolerated. |
| 8 | — | TTS docs say to "write numbers, dates and currency as spoken words" | Read-backs render digits and amounts as words in code (`dialog/readback.py`), which also stops Timbre from regrouping digits. |
| 9 | Voices: "do not guess" | Timbre v2.5 Tamil-preferred voices: **Asmita, Trisha, Brinda, Vedika, Noopur**. English-preferred: Devika, Kaveri, Trupti, Girish, Pranav, Shlok | Defaults `TTS_VOICE_TA=Asmita`, `TTS_VOICE_EN=Kaveri` (change after listening). |
| 10 | — | TTS docs list `voice`/`language` as required; the OpenAPI schema requires only `text`, `model`, `audio_config` | We always send all of them. |
| 11 | `speed` 0.85–1.15 | Confirmed; strings `slow`/`medium`/`fast` also accepted | Numeric only. |

## Confirmed as in the prompt

- Base URL `https://api.vachana.ai`, header `X-API-Key-ID`, optional `X-API-Request-ID` echoed as `request_id`.
- `POST /stt/v3` multipart; `audio_file` ≤ 30 s; WAV/MP3/OGG/FLAC/AAC/M4A (browser WebM is **not** listed → we transcode with ffmpeg).
- v2.5 returns `output.literal` (pre-ITN). v3.0 returns `detected_language_code`, may return `truncated: true`, and a 504 body `{error, code: "UPSTREAM_TIMEOUT", message}`.
- 429 `RATE_LIMITED` "Only 1 active request is allowed at a time", with no `Retry-After` → global semaphore (default 1) + exponential backoff with jitter, 4 attempts. Retry on 429/500/503/504/transport errors only.
- `POST /api/v1/tts/inference` returns raw audio bytes; `timbre-v2.5` and `timbre-v3.0`; voices are per model.

## Deliberate deviation from the build prompt: live STT is not cached

The prompt says "cache every Gnani call". For **live user audio** that would write each victim's spoken
phone, UTR and amount to `.cache/stt/*.json`, which contradicts the rules "never store audio" and "never
log raw PII". It would also save nothing, because every live clip is unique. So `STT_CACHE_LIVE=false` by default:
live turns skip the cache. Bench and probe runs, which use acted or TTS clips, still cache everything, so
re-running a report costs no credits. TTS works the same way: fixed prompts are cached on disk, while read-backs
containing user digits are in-memory only.

## Smoke test findings (2026-11-02)

Clip: `scripts/make_smoke_clip.py`. This is **Timbre-generated** Tamil speech, not an acted human clip, and all
numbers are fake. Calls: 1 TTS to make the clip, 1 STT + 1 TTS in `smoke_gnani.py`, and 1 STT through the app
pipeline. Total: 4 calls.

| Call | Status | Latency |
|---|---|---|
| Prisma v2.5 `ta-IN` `transcribe` (raw, no bias list) | 200 | 1533 ms |
| Prisma v2.5 via app (bias list on) | 200 | 1361 ms |
| Timbre v2.5 `Asmita` `ta-IN`, 24 kHz WAV | 200 | 819 ms (`audio/wav`) |

- **Prisma's Tamil ITN does turn Tamil number words into digits.** `ஐம்பதாயிரம் ரூபாய்` became `₹50,000`,
  and ten spoken Tamil digits became `9876543218`. So the dual-channel design is meaningful: `transcript` has
  digits and `output.literal` has words. On this clip the two channels agreed on both the amount and the phone,
  so both are `confidence=high`.
- ITN dropped the word `நம்பர்` in front of the phone number. Phone cues must not depend on it.
- SBI was transcribed as `எஸ் பை` without the bias list and as `எஸ்பி` with it. Neither was in the alias
  table, so I added them. `எஸ்பி` alone also means a police SP, so it only matches as `எஸ்பி பேங்க்`.
  This shows the bias list changes the output.
- The response matched the docs: `success, request_id, transcript, model, processing_time, end_to_end_latency, output.literal`.

## Probe (2026-11-02): 8 clips × 5 configs = 40 STT calls

**The clips are synthetic.** They are Timbre v2.5 speech (`scripts/make_tts_clips.py`): 5 Tamil voices,
clean audio, fake numbers, one code-mixed clip with English numbers. This is enough to choose settings and find
lexicon gaps. It is **not** a benchmark: n = 8, with no human prosody, no emotion and no noise. Full output is in
`bench/probe/probe_report.md`. The scores below come after the parser fixes the probe triggered; rescoring used
cached responses, so it cost no extra calls.

| config | amount | phone | UTR | bank | median latency |
|---|---|---|---|---|---|
| A v2.5 `verbatim` | 8/8 | 7/8 | 5/8 | 8/8 | 845 ms |
| **B v2.5 `transcribe`** (ITN text; literal identical scores) | **8/8** | **7/8** | 5/8 | **8/8** | 942 ms |
| C v3.0 `transcribe` + topic/keyterms | 7/8 | 7/8 | **7/8** | 7/8 | 1173 ms |
| D v3.0 `codemix` | 8/8 | 6/8 | 7/8 | 8/8 | 1164 ms |
| E v3.0 `transliterate` | 3/8 | 5/8 | 6/8 | 8/8 | 1273 ms |

### What the probe found

1. **The main Prisma error is losing repeated digits.** `1111 2222` became `111 22`, `0000 1` lost a digit, and
   a spoken "zero" in English became "ஜிபே" (GPay). It happens in every config. Chunked read-back exists for
   exactly this.
2. **On B, every wrong number had the wrong length** (4/4: 9 or 11 digits instead of 10 or 12), so the
   phone/UTR validators catch all of them and re-ask. Config C made one *silent* error: it dropped ஒன்றரை and
   returned ₹1,00,000 instead of ₹1,50,000. That is a plausible, valid amount, and only read-back would catch it.
3. **On v2.5 the two channels are not independent.** ITN and `output.literal` agreed on 24/24 readings,
   *including all 4 wrong ones*, because ITN is computed from the same recognition. So agreement does **not**
   detect acoustic errors. It only catches mistakes made in the ITN step itself. The probe found one of those
   (`ஒன்றரை லட்சம்` → `ஒன்றரை 1,00,000`), where the literal channel was right and the case was correctly
   marked low confidence. `confidence=high` therefore means "the parse is internally consistent", not "it is
   correct". Every number is still read back, and the README says this.
4. **Parser gaps fixed:**
   - English number words written in Tamil script (`நைன் எயிட்`, `ஃபிஃப்டி தௌசண்ட் ருபீஸ்`);
   - the Prisma spelling `இருபத்தந்தாயிரம்`;
   - the ITN half-conversion above;
   - romanised v3.0 spellings (`lakshath`, `aiyiram`, `aidhu`, `roobai`, `thollayirathu`).
5. **Safety bugs found and fixed:**
   - The non-financial cue `மிரட்டு` ("threaten") matched every digital-arrest story. Those victims would have
     been sent away from the financial flow.
   - The OTP/PIN check flagged any 4–6 digit number in a turn that mentioned "pin", so "pin போட்டேன், ₹25,000
     போச்சு" would have been dropped. It now requires the digits right after the cue, and not an amount.
6. `transliterate` (E) is the worst config. Its romanisations vary too much (`ambadhaiyiram`, `lakshathai naanu`).

### Decision: keep `STT_MODEL=v2.5`, `STT_FORMAT=transcribe`

- It ties for best on amount, phone and bank. On this set it made no silent amount errors, and every phone/UTR
  error it made is caught by the length check.
- It is about 20% faster than v3.0.
- It returns the literal transcript, which is shown to the user and kept for audit.
- v3.0 `transcribe` was better on UTRs (7/8 vs 5/8), but its errors include a silent wrong amount.

**Revisit after acted human clips are recorded.** If v3.0 still wins on UTR with real speakers, the next
step is a per-field profile: ask the UTR with v3.0 and everything else with v2.5. Gap-fill already knows which
field it is asking for.

## Re-verification (2026-11-04)

Checked `llms.txt`, the REST STT page, the TTS inference page, Available Voices and the changelog. The only
changelog entry since August is Prisma v3.0 (22 Oct 2026): opt-in, "no breaking changes and no deprecations".

| # | Build prompt said | Docs say (2026-11-04) | What the code does |
|---|---|---|---|
| 12 | Fetch the catalog from `/api/TTS/available-voices` | That is a **docs page**, not an API route (`GET api.vachana.ai/api/TTS/available-voices` → 404). No listing endpoint is documented; a voice/model mismatch 400 lists the voices the model supports | Voices stay config values. `Asmita` and `Kaveri` confirmed for `timbre-v2.5` |
| 13 | Telephony output `mulaw`, 8 kHz | `container=mulaw` or `alaw` forces 8000 Hz; `container=raw` + `encoding=pcm_mulaw` is equivalent | Not used yet. Needed by any phone path |
| 14 | "Timbre v2.0 is deprecated" | Only `timbre-v2.5` and `timbre-v3.0` are listed | Code uses `timbre-v2.5` |
| 15 | — | New v3.0 context field `speaker_names` (1–4 names) | Not sent |

Smoke run (2026-11-04, Timbre clip, fake numbers): STT 200 in 3047 ms, TTS 200 in 593 ms, response shape as documented.

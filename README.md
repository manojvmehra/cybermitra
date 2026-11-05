# CyberMitra TN

An **AI-first voice intake agent for Tamil Nadu's 1930 cyber-fraud helpline overflow**.

1. A victim speaks Tamil, Tanglish or English on the caller page (a phone browser).
2. The AI handles the whole call: it takes the story, captures **every transaction** (amount, time, UTR),
   the victim's bank and the suspect's details. **Gnani Prisma** transcribes; every number is converted
   **deterministically in code**; digits are read back in chunks with **Gnani Timbre**; the caller corrects
   them by voice, ✓/✗ buttons, a keypad, or by pasting the bank SMS.
3. It closes with next-steps guidance in the caller's language and a summary with a draft reference
   (`CM-DRAFT-xxxx`, never presented as an NCRP acknowledgement).
4. It pushes a **Complaint Packet** (CFCFRMS field order) to an **operator review queue** on a second device.
   The operator reviews, edits if needed, and approves, instead of typing the complaint from scratch.
5. A call goes to a person only when the caller asks, the AI cannot understand, or the case is non-financial
   or an emergency. The handoff is **warm**: the operator gets the masked transcript and everything captured
   so far. In this demo the transfer is **simulated**.

> It does **not** file on NCRP/CFCFRMS, contact banks or police, freeze or recover money, or auto-approve.
> **Core rules:** a language model never decides a digit (code converts digits, a human confirms digits).
> The AI handles the call; a human approves the complaint. Approve only changes a status.

Built for the Gnani AI "Great Indian AI Internship Challenge 2026" (target: *Mixed Vibes*, best code-mixed voice build).

## Gnani models used

| Model | Exact model string | Use |
|---|---|---|
| Gnani Prisma v2.5 (STT) | `prisma-v2.5` (default; `model` omitted) | Speech-to-text with `format=transcribe`, which returns both ITN digits and the pre-ITN `output.literal` |
| Gnani Prisma v3.0 (STT) | `prisma-v3.0` | Optional (`STT_MODEL=v3.0`); compared in the probe |
| Gnani Timbre v2.5 (TTS) | `timbre-v2.5` | All prompts and digit read-backs (voices `Asmita` ta-IN, `Kaveri` en-IN) |
| Gnani Evon v3.3 (LLM) | `gnani-evon-v3.3-30B-A3B` | **Optional, off by default** (`EVON_MODE=off`). If enabled, it can only propose verbatim *spans*; numbers.py parses them |

## Quick start

```bash
make setup
```

```bash
cp .env.example .env
```

Put your `GNANI_API_KEY` in `.env`, then:

```bash
make run
```

Open http://localhost:8080 on the caller device and http://localhost:8080/operator on the operator device
(set `OPERATOR_TOKEN` in `.env` first; the operator API is off without it). Requirements: Python 3.11+ and `ffmpeg` on PATH (browser audio is WebM/Ogg,
which Prisma does not accept, so we transcode in memory).

Day-1 order (each step asks before spending more than a few calls):

```bash
python scripts/smoke_gnani.py
```

```bash
python scripts/probe_prisma_formats.py --clips 8
```

```bash
python scripts/prerender_prompts.py
```

## Experimental telephony (off by default)

Call a real number and talk to the same agent. Calls go through the same FSM, queue and operator review, and appear
as `experimental telephony`. It needs a Twilio number and a public HTTPS URL.

1. Run `ngrok http 8080`.
2. In `.env`, set `TWILIO_ENABLED=true`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `TWILIO_PUBLIC_URL=https://<your-ngrok-host>`, then start the server.
3. In the Twilio console, under your number's voice settings, set "A call comes in" to Webhook, HTTP POST, `https://<your-ngrok-host>/api/twilio/voice`.
4. Call the number. Keys: **1** yes, **2** no, **3** repeat, **0** officer, `*` to type a number, then `#` to finish.

Limits: half duplex (you are heard only after the AI finishes speaking; a key interrupts it), turns end after 1.2 s of
quiet, one language per server (`TWILIO_LANG`), no SMS paste, and no real transfer to a person. A free ngrok URL
changes each run, which means updating `.env` and the Twilio console.

## Tests and quality

```bash
make test
```

```bash
make lint
```

All Gnani calls are mocked with `respx` in the tests (429→200, 504→200, 401, 402, empty transcript,
`truncated: true`). The FSM is pure and is tested with scripted dialogs and no network.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). API deviations found while verifying the docs:
[docs/API_NOTES.md](docs/API_NOTES.md).

```
caller.html ─► FastAPI ─► ffmpeg ─► Prisma ─► safety ─► FSM (numbers · timeparse · sms_parser · validators · yesno)
                                                          ├► readback (digit words) ─► Timbre
                                                          └► packet ─► queue (fair order, audit) ─SSE─► operator.html
```

Caller (`app/api/routes_caller.py`):

| Endpoint | Purpose |
|---|---|
| `POST /api/session` | `{lang, consent}` → opening prompt |
| `POST /api/session/{id}/turn` | multipart `audio` (up to `MAX_TURN_S`; split into pieces for Prisma) |
| `POST /api/session/{id}/sms` | pasted bank SMS, one or several (0 API calls) |
| `POST /api/session/{id}/confirm` | ✓/✗ for a read-back chunk, or for `more_txn` / `review` / `dup_utr` / `called_bank` |
| `POST /api/session/{id}/numpad` | typed value (authoritative), `{field, txn_index?, digits}` |
| `POST /api/session/{id}/skip` | skip a field (or `more_txn`) |
| `POST /api/session/{id}/human` | "Talk to a person": warm handoff |
| `GET /api/session/{id}/summary` | Victim Summary + next steps |
| `DELETE /api/session/{id}` | wipe |
| `GET /api/audio/{sha}.wav` | TTS audio |
| `GET /api/metrics` | containment, handoffs by reason, median handling / approval time, Gnani p50/p95 (no PII) |
| `GET /health` | key present, Evon mode, ffmpeg, operator enabled |

Operator (`app/api/routes_operator.py`, header `X-Operator-Token`):

| Endpoint | Purpose |
|---|---|
| `GET /api/operator/queue` | handoffs, review queue (with "why here"), recent decisions, audit log, live calls |
| `GET /api/operator/packet/{pid}` | packet JSON + text (+ masked transcript for handoffs); starts the approval clock |
| `POST /api/operator/packet/{pid}/claim` | take a handoff |
| `POST /api/operator/packet/{pid}/edit` | `{field, txn_index?, value}`, validated; sets `source=operator` |
| `POST /api/operator/packet/{pid}/approve` | status only: no network call, no submission |
| `POST /api/operator/packet/{pid}/reject` | `{reason}` |
| `GET /api/events` | SSE: `packet_created`, `packet_updated`, `queue_reordered`, `live_fields` |

## Benchmark

Every number below comes from `bench/run_benchmark.py` + `bench/report.py` on real API output (n + Wilson
95% CI). `report.py` writes [bench/RESULTS.md](bench/RESULTS.md) and copies it between the markers; nothing
here is typed by hand.

<!-- RESULTS:START (generated by bench/report.py, do not edit) -->
### Benchmark results (generated)

Generated by `bench/report.py` from `bench/results/run.jsonl`. Prisma v2.5, format `transcribe`.
8 clips (8 **TTS-generated**, 0 acted by people), 5 voices, 16 clip×condition runs (0 API errors). Cells: k/n = % [Wilson 95% CI].

> **These clips are machine speech (Timbre TTS): clean, unemotional, read from a script. They show how the pipeline behaves, not how it does on real victims. Replace with acted human clips.**

## Field exact-match before read-back

| field | clean | tel8k | all |
|---|---|---|---|
| amount | 8/8 = 100% [68–100] | 8/8 = 100% [68–100] | 16/16 = 100% [81–100] |
| bank | 8/8 = 100% [68–100] | 8/8 = 100% [68–100] | 16/16 = 100% [81–100] |
| suspect_phone | 7/8 = 88% [53–98] | 7/8 = 88% [53–98] | 14/16 = 88% [64–97] |
| utr | 5/8 = 62% [31–86] | 6/8 = 75% [41–93] | 11/16 = 69% [44–86] |

## Dual-channel agreement (ITN transcript vs `output.literal`)

| field | agreement rate | accuracy when agree | accuracy when disagree (either channel) |
|---|---|---|---|
| amount | 16/16 = 100% [81–100] | 16/16 = 100% [81–100] | — |
| suspect_phone | 16/16 = 100% [81–100] | 14/16 = 88% [64–97] | — |
| utr | 15/16 = 94% [72–99] | 10/15 = 67% [42–85] | 1/1 = 100% [21–100] |

## Number format breakdown (extractor `method`)

| field | method | exact |
|---|---|---|
| amount | english_words | 2/2 = 100% [34–100] |
| amount | itn_digits | 10/10 = 100% [72–100] |
| amount | tamil_words | 4/4 = 100% [51–100] |
| bank | none | 16/16 = 100% [81–100] |
| suspect_phone | english_words | 2/2 = 100% [34–100] |
| suspect_phone | itn_digits | 12/12 = 100% [76–100] |
| suspect_phone | none | 0/2 = 0% [0–66] |
| utr | itn_digits | 10/10 = 100% [72–100] |
| utr | mixed | 1/1 = 100% [21–100] |
| utr | none | 0/5 = 0% [0–43] |

## Read-back SIMULATION (oracle user, not real users)

An oracle answers yes/no per chunk against ground truth. This measures *how much correcting the user would have to do*, not accuracy.

| field | n | missing (needs full re-ask) | mean chunk corrections (when present) | would end unconfirmed |
|---|---|---|---|---|
| amount | 16 | 0 | 0.00 | 0 |
| suspect_phone | 16 | 2 | 0.00 | 0 |
| utr | 16 | 5 | 0.00 | 0 |

## Call SIMULATION (real FSM over the saved transcripts; oracle caller)

`bench/simulate_calls.py` replays each clip's real Prisma transcript as the caller's story, then an oracle answers every read-back against ground truth and types what the story did not give. No API calls. **This is a simulation, not a user study.** The oracle never asks for a person and always knows the answer, so containment here only shows the dialogue does not dead-end.

- Simulated calls: 16 (16 from TTS clips)
- Containment (ended `ready_for_review`, no human): 16/16 = 100% [81–100]
- Handoffs by reason: none
- Intended handoffs caught (recall): — (no handoff scripts in this run); handoffs that were intended (precision): — (no handoffs)
- **Wrong digits that reached the packet as confirmed: 0** (0 by design: every digit is confirmed chunk by chunk or typed)
- Simulated handling time, median: 143 s = caller clips + STT latency + prompt speech estimated at 13 chars/s; excludes the caller's thinking and typing time

| field | read-back corrections | typed (voice gave no valid value) | left unconfirmed |
|---|---|---|---|
| suspect_phone | 0 | 2 | 0 |
| utr | 0 | 5 | 0 |

## Cost and latency

- Live STT calls in this run: 16 (cached: 0)
- STT latency p50 / p95 (live calls): 1306 ms / 1958 ms

## Limitations

- TTS-generated clips (clean machine speech, no emotion, no real background noise); small n — read the confidence intervals.
- 'missing' means the number came out the wrong length and was rejected by validation, so the app asks again; it is not a silent wrong value.
- Telephone band is simulated (band-pass + 8 kHz µ-law), not a real phone line.
- Read-back numbers are a simulation with a perfect user.
<!-- RESULTS:END -->

To run it on acted human clips (the real benchmark):

1. Record the 8 acted scripts in [bench/SCRIPTS.md](bench/SCRIPTS.md) (synthetic numbers only) as
   `bench/corpus/<clip_id>.wav`, and update `bench/manifest.jsonl`.
2. Put recorded street/bus noise in `bench/noise/*.wav`.
3. Run:

```bash
make bench
```

Conditions: `clean`, `snr10`, `snr5`, `tel8k` (300–3400 Hz, 8 kHz µ-law round trip), `snr10_tel8k`.
The benchmark reports agreement between the ITN and literal parses. The Prisma probe found that on v2.5
the two channels agree even when both are wrong (24/24 readings, 4 of them wrong), because ITN is computed
from the same recognition. So agreement only catches ITN-stage glitches; read-back and the length checks
catch the acoustic errors. Details are in [docs/API_NOTES.md](docs/API_NOTES.md). The read-back numbers are an *oracle simulation* and are reported as corrections needed,
not as a post-read-back accuracy figure.

## Limitations (honest)

- The corpus is small, acted by team members, and synthetic. Expect wide confidence intervals.
- Benchmark telephone-band audio is simulated, not a real phone line.
- The Tamil number lexicon must be reviewed by a native speaker against what Prisma actually emits
  (see `app/nlp/lexicon_ta.py`). Prisma's spellings may differ from ours.
- `confidence=high` means "the ITN and literal parses agree", not "correct". On v2.5 they are not independent,
  so every number is still read back.
- The STT settings were chosen from a probe on 8 **TTS-generated** clips, not human speech. Revisit after
  acted clips are recorded.
- Evon is off by default. The app is fully functional without it.
- The rule extractor's narrative attribution (which number is the suspect's) is best-effort. Gap-fill
  questions plus read-back are the safety net.
- The handoff to a person is **simulated**: the operator sees the packet and transcript, but no phone call is
  bridged. Telephony is experimental, off by default and not yet tested on a real call. There is no NCRP/CFCFRMS integration; "approve" changes a status in memory.
- Containment and handling time come from a **simulation** (`bench/simulate_calls.py`: real transcripts, an
  oracle caller). They show the dialogue does not dead-end; they are not measurements on real callers.
- Next-steps lines are tagged "draft guidance" until each has an official source in
  [docs/NEXT_STEPS_SOURCES.md](docs/NEXT_STEPS_SOURCES.md).
- Queue and sessions are in memory: a restart empties them (by design, no database).
- Tele-MANAS (14416) and the other helpline numbers must be re-verified from official sources before submission.

## Safety and privacy

- Use synthetic data only. Never enter real phone numbers, account numbers, Aadhaar or PAN.
- **Nothing the user says reaches disk.**
  - Audio stays in memory, including uploads over 1 MB, which Starlette would otherwise spool to a temp file.
  - Live transcripts are not cached (`STT_CACHE_LIVE=false`).
  - Read-back audio, which speaks the user's digits, is held in memory for 10 minutes. It is served from a
    random URL with `no-store`. Only the fixed prompts are cached on disk.
- **Logs are JSON, and every line is masked** (`98•••••210`, `4306••••7418`), including uvicorn's access log.
  Check them with:
  ```bash
  python scripts/check_logs_pii.py logs
  ```
- **ffmpeg runs untrusted audio sandboxed:** `-protocol_whitelist pipe` stops m3u8/concat files from reading local
  files, `-t` caps the decoded length, and a timeout kills it.
- **Request limits:**
  - body size is capped, including chunked uploads (7 MB audio, 16 KB JSON);
  - request schemas are strict;
  - every STT call counts toward the per-call cap (`MAX_TURNS_PER_CALL`, then a warm handoff), along with
    per-IP and global session caps.
  - the operator API needs `X-Operator-Token` (compared in constant time); the SSE stream is read with
    `fetch` so the token never appears in a URL, and the page keeps it in memory only.
  - Behind a proxy, set `TRUST_PROXY_HEADERS=true`; it is off by default because the header can be spoofed.
- **Browser hardening:**
  - a CSP that allows only the page's own script, by hash;
  - `frame-ancestors 'none'`, `nosniff`, `no-referrer`, and a permissions policy allowing only the microphone;
  - `/docs` is off unless `ENABLE_DOCS=true`.
- **The app never asks for OTP, PIN, CVV, password, full account number, Aadhaar or PAN.** If one is spoken
  right after its cue word, it is dropped and never echoed. Amounts and normal stories mentioning "pin" are not dropped.
- **Hand-offs:** sextortion and harassment go to a non-financial hand-off; digital-arrest threats do not.
  Self-harm cues stop intake and show Tele-MANAS 14416 and 1930.
- **The Docker image runs as a non-root user.** Set `GNANI_API_KEY` in the host's dashboard, never in the repo
  or in `.env.example`.

*Not affiliated with MHA, I4C, NCRP or Tamil Nadu Police.*

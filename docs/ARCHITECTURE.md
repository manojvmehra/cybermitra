# Architecture

**Core rule:** a language model never decides a digit. Code converts digits. A human confirms digits.

**Second rule:** the AI handles the call; a human approves the complaint. Approve only changes a status.

```
CALLER DEVICE (static/caller.html)                OPERATOR DEVICE (static/operator.html, X-Operator-Token)
mic + silence stop · SMS paste · phone keypad     handoffs · review queue · packet view · edit/approve/reject
  │ multipart audio / JSON                           ▲ SSE /api/events (fetch stream, token in header)  │ JSON
  ▼                                                  │                                                  ▼
FastAPI app/main.py ─ app/api/routes_caller.py ──────┴─ app/api/events.py ◄── app/api/routes_operator.py
  ├─ audio.normalize        ffmpeg pipes → 16 kHz mono WAV (in memory, never on disk)
  ├─ gnani.stt.transcribe   Prisma REST · SHA-256 cache · semaphore(1) · retry/backoff
  ├─ dialog.state_machine   pure next_state(session, event) → (session, actions)
  │    ├─ nlp.safety        OTP/PIN/ID drop · non-financial / wellbeing hand-offs
  │    ├─ nlp.extractor     narrative rules: every loss amount → one transaction (+ optional Evon spans)
  │    ├─ nlp.numbers       Tamil / Tanglish / English / ITN digits → int or digit string
  │    ├─ nlp.timeparse     "nethu saayangaalam", "12 nimisham munnadi" → datetime + precision
  │    ├─ nlp.sms_parser    pasted SMS (one or many) → one transaction each (0 API calls)
  │    ├─ nlp.validators    phone / UTR / UPI / amount / datetime
  │    ├─ nlp.yesno         yes / no / correction / repeat / human; any "no" wins
  │    └─ dialog.readback   chunking (5+5, 4+4+4) + digit words joined by commas; times as phrases
  ├─ gnani.tts.synthesize   Timbre REST · static prompts cached, read-back audio in memory only
  ├─ dialog.packet          Complaint Packet (CFCFRMS order, text + JSON) · Victim Summary
  └─ queue.store/priority   in-memory packets · status transitions · fair order · audit log
State: in-memory dicts (sessions TTL 30 min, packets TTL 24 h). No database.
```

## Number pipeline

1. `normalise_text`: NFC, Tamil digits → ASCII, lowercase Latin, punctuation → space (except `₹ , . @`).
2. `words` → `tokenize`. Each word is ITN digits, a whole-word special (currency, filler, "double", "and",
   "a", "hundred"), or is **segmented** by `_segment`: a memoised search for the fewest-token full cover over
   the stem table. It understands Tamil sandhi in both scripts:
   - a word ending in `ு` / `u` drops it before a vowel: `ஐம்பது+ஆயிரம் → ஐம்பதாயிரம்`, `aimbadhu+aayiram → aimbadhaayiram`;
   - the vowel sign tells us the next word's first vowel: `இருபத்து+ஐந்து → இருபத்தைந்து`, `ஒன்று+அரை → ஒன்றரை`;
   - case suffixes are allowed after a number (`ஆயிரத்துக்கு`, `ettula`).
   If two segmentations have the same minimal length and different values, the token is flagged `ambiguous`.
   We return a warning rather than guess.
3. `_group_spans`: number words in a row, with at most one filler between them; any other word ends the span.
4. Amounts: Indian grammar `(a×1e7)+(b×1e5)+(c×1000)+(d×100)+e`. Slots must arrive in decreasing order, and
   a grammar break starts a new candidate. A fraction is valid only before a multiplier. A bare unit ("oru call")
   is not an amount. "rendu moonu latcham" is flagged as a `range`. Several different amounts with no unique
   currency marker give `multiple_amounts`.
5. Digit strings: single digits, `double`/`triple`, tens + unit pairs ("ninety eight" → 98), and ITN digit
   runs. With `expected_len`, separate spans are joined only when the result is exactly that length.

## Dual-channel confidence (Prisma v2.5, `format=transcribe`)

One call returns `transcript` (ITN digits) and `output.literal` (spoken words). Each channel is parsed
independently. If the two values agree, confidence is `high`. If they disagree, or only one channel parses, it is `low`.
In that case the literal parse is read back and the numpad is offered first. Both cases are always read back.

## Dialogue FSM

```
CONSENT → OPENING → NARRATIVE
  → TXN loop[i]: GAP_FILL(amount → datetime → utr|sms) ⇄ READBACK → ASK_MORE_TXN ↺ (only when MAX_TXNS > 1; default 1 skips it)
  → CASE: GAP_FILL(victim_bank → payment_mode → suspect_phone → suspect_upi? → suspect_bank? → called_bank
                   → district → victim_name → victim_mobile) ⇄ READBACK
  → REVIEW ("2 transactions, total ₹50,000. Is everything correct?") → NEXT_STEPS spoken → QUEUED
any → HANDOFF_HUMAN | HANDOFF_NONFIN | HANDOFF_WELLBEING      (DUP_CHECK: a UTR heard twice)
```

- The opening (always) says: AI assistant, not the police, cannot freeze money, call the bank / 1930 now,
  never asks for OTP/PIN.
- Gap-fill asks one field at a time, so the slot is known from the question. With more than one transaction
  every question and read-back starts "Transaction n:".
- The story seeds one transaction per loss amount (a figure next to "total" is skipped). "rendu thadava" /
  "moonu transaction" sets the expected count, used only to remind the caller before "any other transaction?".
- One pasted SMS = one transaction; several SMS at once (blank lines, or one block with several debits) give
  several. SMS values are `confirmed`, `source=sms`, never re-read by voice. A UTR already in the call is not
  added twice. Numpad / typed input is authoritative.
- A spoken UTR equal to an earlier transaction's → DUP_CHECK: "same transaction?" yes drops the duplicate,
  no re-asks (one repair).
- Read-back confirms each chunk. A NO opens correction mode. "illa, kadaisi ettu" → positional correction.
  Re-saying the whole number is also accepted. Times are read as a phrase that matches their precision
  ("yesterday, evening"), and a story that only says "nethu" asks for the time instead of reading back a noon.
- Each field gets at most 2 repairs. After that it is `unconfirmed` (packet: `⚠ verify`, highlighted).
- Escalation → HANDOFF_HUMAN (warm: the packet so far + masked transcript go to the operator):
  the caller asks ("aal venum", the button); `SILENCE_HANDOFF_COUNT` empty turns; `MAX_TURNS_PER_CALL`;
  3 unclear answers in a row to a yes/no question; a second field that runs out of repairs (our reading of
  "2 failed repairs and the numpad declined": the numpad is on screen from the first failure, so a caller who
  still cannot give a second field needs a person).
- A spoken OTP, PIN, CVV or ID is dropped, never echoed, and the previous question is asked again.

## Experimental telephony (off by default)

`TWILIO_ENABLED=true` with an auth token mounts `app/api/routes_twilio.py`. Each phone call is one normal `Session`
with `channel="phone"`; only the transport differs.

```
Twilio ─ POST /api/twilio/voice ─► signature check ─► TwiML <Connect><Stream> + one-time token
       ─ WS /api/twilio/stream ──► app/twilio_bridge.py CallBridge
            µ-law 8 kHz → Endpointer (cuts turns by energy) → 16 kHz WAV → routes_caller.process_wav → same FSM
            keys 1 2 3 0 * # → BUTTON / NUMPAD / HUMAN events → same FSM
            Timbre (container=mulaw, 8 kHz) ← spoken prompts          routes_caller.commit → same queue + SSE
```

- `routes_caller.commit` and `process_wav` are the shared turn steps, so the web and phone paths cannot drift apart.
- The receive loop never waits: it feeds the endpointer and fills an inbox. One worker handles turns and keys in order.
- `mark` events say when audio finished playing. Only then does the bridge listen, so the AI never hears itself.
- `PHONE_<id>` prompts replace anything that mentions a screen. The opening says the service is experimental.
- If TTS fails or the bridge hits a bug, the stream closes and the TwiML after `<Connect>` tells the caller to call 1930.
- Audio stays in memory for one turn. Twilio records nothing because we never ask it to: no `<Record>`, no `<Gather>`.
  `From` is used only as an HMAC key for rate limiting; it is not logged or stored.

## Review queue (`app/queue`)

- Handoffs: wellbeing first, then FIFO. Review: items waiting > `QUEUE_MAX_WAIT_S` first (FIFO), then by the
  latest **confirmed** debit time, freshest first, then items with no confirmed time in arrival order.
  **The amount is never read** (`tests/test_priority.py` shuffles amounts and checks the order is unchanged,
  and checks `total_amount` is never called).
- Every position change is written to the audit log with its reason (`overdue…`, `confirmed last debit…`,
  `arrival order`); edits and status changes are audited with the field name only, never the value.
- Status: `ready_for_review → approved | rejected`; `needs_human → claimed → approved | rejected`.
  Anything else is 409. An edit is validated like the call itself and sets `source="operator"`.
  `approval_latency_s` = packet opened → approved. Approve makes no network call (tested with respx).
- A 15 s timer re-ranks (time alone makes items overdue) and pushes `queue_reordered` over SSE.

## Privacy

| Data | Where it lives | How long |
|---|---|---|
| Uploaded audio | request memory (multipart spooling raised to the body limit, so nothing touches disk) | one request |
| Transcript, fields | in-memory session dict | until `DELETE` or `SESSION_TTL_S` (30 min) |
| Packets (fields; masked transcript for handoffs only) | in-memory queue store | `PACKET_TTL_S` (24 h) |
| Live STT responses | not cached (`STT_CACHE_LIVE=false`) | — |
| Read-back audio (speaks the user's digits) | in-memory, random 256-bit token URL, `Cache-Control: no-store` | `EPHEMERAL_AUDIO_TTL_S` (10 min) |
| Fixed prompt audio (no user data) | `.cache/tts/<sha256>.wav` | until deleted |
| Bench / probe STT results (acted or TTS clips) | `.cache/stt/<sha256>.json` | until deleted |
| Logs | stdout (+ `LOG_FILE`), JSON, every line through `mask()`; ids and audio tokens cut to 8 characters | rotating 3 × 5 MB |
| Phone audio | memory, one turn | one turn |

Request path hardening is in `app/security.py` (body limit, headers, CSP hash, client IP) and `app/audio.py` (ffmpeg).
`DEMO_MODE` shows a banner warning users not to enter real details.

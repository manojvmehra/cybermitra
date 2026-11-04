"""Experimental telephony: one Twilio media stream <-> one normal Session.

Only the transport is new. Audio is converted between Twilio's 8 kHz µ-law and our 16 kHz pipeline, speech is
cut into turns by an energy endpointer (a phone has no push-to-talk), and the keypad stands in for the buttons
and numpad. Every turn then goes through the same FSM, packet, queue and operator review as the web page.
Audio stays in memory for one turn; nothing here touches the disk.
"""

import asyncio
import base64
import io
import json
import logging
import wave
from collections import deque
from collections.abc import Awaitable, Callable, Sequence

import numpy as np

from app import audio
from app.api import routes_caller
from app.config import get_settings
from app.dialog import prompts
from app.dialog.models import DIGIT_FIELDS, Action, Event, Session
from app.dialog.state_machine import TERMINAL, next_state
from app.gnani import tts
from app.gnani.http import GnaniError
from app.logging_utils import log

logger = logging.getLogger("api")

RATE = 8000
MS = RATE // 1000  # samples per millisecond
MIN_RMS = 300.0  # quieter than this is never speech
NOISE_FACTOR = 3.0  # speech must be this far above the line's noise floor
START_MS = 120  # this much sound in a row starts a turn
PREROLL_MS = 300  # kept from before the start, so the first syllable is not cut
END_SILENCE_MS = 1200  # a turn ends after this much quiet; people pause between digit groups
NO_SPEECH_MS = 10000  # nothing heard for this long counts as a silent turn
MIN_SPEECH_MS = 200  # shorter bursts are a click or a cough
CHUNK_BYTES = 8000  # one second of audio per outbound message
MAX_KEYED_DIGITS = 16
KEYPAD_FIELDS = {*DIGIT_FIELDS, "amount"}  # a phone keypad can only enter numbers
YES_NO_STATES = {"ASK_MORE_TXN": "more_txn", "REVIEW": "review", "DUP_CHECK": "dup_utr"}


# ---------------------------------------------------------------- µ-law (ITU-T G.711)
def _decode_table() -> np.ndarray:
    u = ~np.arange(256) & 0xFF
    magnitude = (((u & 0x0F) << 3) + 0x84) << ((u & 0x70) >> 4)
    return np.where(u & 0x80, 0x84 - magnitude, magnitude - 0x84).astype(np.int16)


_DECODE = _decode_table()


def mulaw_to_pcm(data: bytes) -> np.ndarray:
    return _DECODE[np.frombuffer(data, dtype=np.uint8)]


def pcm_to_mulaw(pcm: np.ndarray) -> bytes:
    x = pcm.astype(np.int32)
    sign = (x < 0).astype(np.int32) << 7
    mag = np.minimum(np.abs(x), 32635) + 0x84
    exponent = np.clip(np.floor(np.log2(mag)).astype(np.int32) - 7, 0, 7)
    mantissa = (mag >> (exponent + 3)) & 0x0F
    return (~(sign | (exponent << 4) | mantissa) & 0xFF).astype(np.uint8).tobytes()


def mulaw8k_to_wav16k(data: bytes) -> bytes:
    """Twilio inbound audio -> the 16 kHz mono WAV the rest of the pipeline uses."""
    pcm = mulaw_to_pcm(data).astype(np.float32)
    up = np.interp(np.arange(len(pcm) * 2) / 2, np.arange(len(pcm)), pcm)
    return audio.pcm_to_wav(np.round(up).astype(np.int16).tobytes(), 16000)


def wav_to_mulaw8k(wav_bytes: bytes) -> bytes:
    """Any mono/stereo 16-bit WAV -> raw 8 kHz µ-law, low-passed first so nothing above 4 kHz folds back."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        rate, channels = w.getframerate(), w.getnchannels()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1)
    if rate > RATE:
        n = np.arange(-32, 33)
        cutoff = 3800 / rate
        taps = 2 * cutoff * np.sinc(2 * cutoff * n) * np.hamming(len(n))
        pcm = np.convolve(pcm, taps / taps.sum(), mode="same")
    positions = np.arange(int(len(pcm) * RATE / rate)) * rate / RATE
    return pcm_to_mulaw(np.interp(positions, np.arange(len(pcm)), pcm))


def to_phone_audio(data: bytes) -> bytes:
    """Twilio plays header bytes as noise, so a WAV that arrives here is converted, never passed on."""
    return wav_to_mulaw8k(data) if data[:4] == b"RIFF" else data


# ---------------------------------------------------------------- endpointing
class Endpointer:
    """Cuts a µ-law stream into spoken turns by energy. It counts audio, not wall-clock time."""

    def __init__(self, max_clip_s: float) -> None:
        self.max_samples = int(max_clip_s * RATE)
        self.reset()

    def reset(self) -> None:
        self.preroll: deque[bytes] = deque()
        self.preroll_n = self.waited = self.run = self.quiet = self.voiced = 0
        self.noise = MIN_RMS / NOISE_FACTOR
        self.speech: bytearray | None = None

    def feed(self, frame: bytes) -> tuple[str, bytes | None]:
        """-> ("", None) | ("speech", µ-law bytes of the turn) | ("no_speech", None)"""
        n = len(frame)
        if not n:
            return "", None
        pcm = mulaw_to_pcm(frame).astype(np.float32)
        rms = float(np.sqrt(np.mean(pcm ** 2)))
        loud = rms > max(MIN_RMS, self.noise * NOISE_FACTOR)
        if self.speech is None:
            return self._before_speech(frame, n, rms, loud)
        self.speech += frame
        self.voiced += n if loud else 0
        self.quiet = 0 if loud else self.quiet + n
        if self.quiet < END_SILENCE_MS * MS and len(self.speech) < self.max_samples:
            return "", None
        turn, voiced = bytes(self.speech), self.voiced
        self.reset()
        return ("speech", turn) if voiced >= MIN_SPEECH_MS * MS else ("", None)

    def _before_speech(self, frame: bytes, n: int, rms: float, loud: bool) -> tuple[str, bytes | None]:
        self.preroll.append(frame)
        self.preroll_n += n
        while self.preroll and self.preroll_n - len(self.preroll[0]) >= PREROLL_MS * MS:
            self.preroll_n -= len(self.preroll.popleft())
        self.waited += n
        if loud:
            self.run += n
        else:
            self.run = 0
            self.noise = 0.95 * self.noise + 0.05 * rms
        if self.run >= START_MS * MS:
            self.speech = bytearray(b"".join(self.preroll))
            self.voiced = self.run
            self.quiet = 0
        elif self.waited >= NO_SPEECH_MS * MS:
            self.reset()
            return "no_speech", None
        return "", None


# ---------------------------------------------------------------- one call
class CallBridge:
    """Half duplex: the caller is heard only when the AI is not speaking. Keys work at any time."""

    def __init__(self, send: Callable[[str], Awaitable[None]], close: Callable[[], Awaitable[None]],
                 lang: str, call_ref: str) -> None:
        self.send, self.close = send, close
        self.lang, self.call_ref = lang, call_ref
        self.stream_sid = ""
        self.s = Session(lang=lang, channel="phone")  # type: ignore[arg-type]
        self.inbox: asyncio.Queue[tuple[str, bytes | str | None]] = asyncio.Queue()
        self.endpointer = Endpointer(get_settings().MAX_CLIP_S)
        self.listening = False
        self.playing_mark = ""  # the mark that ends the audio now playing
        self.marks = 0
        self.ending = False  # the last thing is being said: hang up when it has played
        self.keyed: str | None = None  # digits typed so far; None when the keypad is not in entry mode
        self.entry_field: tuple[str, int | None] | None = None
        self.last_audio = b""

    # ---- called by the receive loop; these never wait for STT or TTS
    async def on_message(self, msg: dict) -> None:
        event = msg.get("event")
        if event == "media":
            self._on_media(msg.get("media") or {})
        elif event == "dtmf":
            digit = str((msg.get("dtmf") or {}).get("digit", ""))
            if digit and digit in "0123456789*#":
                self.inbox.put_nowait(("key", digit))
        elif event == "mark":
            self._on_mark(str((msg.get("mark") or {}).get("name", "")))
        elif event == "stop":
            self.inbox.put_nowait(("stop", None))

    def _on_media(self, media: dict) -> None:
        if not self.listening or media.get("track", "inbound") != "inbound":
            return
        try:
            frame = base64.b64decode(media.get("payload", ""), validate=True)
        except ValueError:
            return
        kind, turn = self.endpointer.feed(frame)
        if kind:
            self.listening = False  # one turn at a time; the reply reopens the microphone
            self.inbox.put_nowait((kind, turn))

    def _on_mark(self, name: str) -> None:
        if not name or name != self.playing_mark:
            return  # a mark for audio that was cleared
        self.playing_mark = ""
        if self.ending:
            self.inbox.put_nowait(("close", None))
        else:
            self.endpointer.reset()
            self.listening = True

    # ---- the worker: everything that changes the call runs here, one thing at a time
    async def run(self) -> None:
        log(logger, "phone call started", call=self.call_ref)
        try:
            await self._loop()
        except Exception:  # never leave a caller on a silent line; TwiML tells them to call 1930
            logger.exception("phone call failed")
            await self.close()

    async def _loop(self) -> None:
        await self._apply(*next_state(self.s, Event(type="START")))
        while True:
            kind, value = await self.inbox.get()
            if kind == "stop":
                self._caller_left()
                return
            if kind == "close":
                await self.close()
                return
            if self.ending:
                continue
            if kind == "key":
                await self._key(str(value))
            elif kind == "speech":
                await self._speech(bytes(value or b""))  # type: ignore[arg-type]
            elif kind == "no_speech":
                await self._apply(*next_state(self.s, Event(type="TIMEOUT")))

    async def _speech(self, turn: bytes) -> None:
        self.keyed = None  # a spoken answer replaces anything half typed
        if self.s.api_turns >= get_settings().MAX_TURNS_PER_CALL:
            await self._apply(*next_state(self.s, Event(type="HUMAN", text="max_turns")))
            return
        s, acts, _, _ = await routes_caller.process_wav(self.s, mulaw8k_to_wav16k(turn))
        await self._apply(s, acts)

    async def _key(self, key: str) -> None:
        if self.playing_mark:  # a key interrupts the AI
            await self.send(json.dumps({"event": "clear", "streamSid": self.stream_sid}))
        self.endpointer.reset()
        if self.keyed is not None:
            await self._entry_key(key)
        elif key == "0":
            await self._apply(*next_state(self.s, Event(type="HUMAN")))
        elif key == "3":
            await self._play(self.last_audio)
        elif key in "12":
            await self._answer("yes" if key == "1" else "no")
        elif key == "*" and self._numeric_field():
            self._begin_entry(*self._numeric_field())  # type: ignore[misc]
            await self._speak_id("USE_NUMPAD")
        else:
            await self._resume()

    async def _answer(self, answer: str) -> None:
        """1 and 2 are the ✓ and ✗ buttons: authoritative, and only where a yes or no is being asked."""
        s, rb = self.s, self.s.readback
        if s.state == "READBACK" and rb is not None:
            if rb.awaiting == "correct":  # this field cannot be typed; repeat the request
                await self._play(self.last_audio)
                return
            ev = Event(type="BUTTON", field=rb.field, txn_index=rb.txn_index, chunk_index=rb.index,
                       answer=answer)  # type: ignore[arg-type]
        elif s.state in YES_NO_STATES:
            ev = Event(type="BUTTON", field=YES_NO_STATES[s.state], answer=answer)  # type: ignore[arg-type]
        elif s.state == "GAP_FILL" and s.current_field == "called_bank":
            ev = Event(type="BUTTON", field="called_bank", answer=answer)  # type: ignore[arg-type]
        else:
            await self._resume()
            return
        await self._apply(*next_state(s, ev))

    async def _entry_key(self, key: str) -> None:
        assert self.entry_field is not None and self.keyed is not None
        if key == "#":
            field, txn = self.entry_field
            digits, self.keyed = self.keyed, None
            await self._apply(*next_state(self.s, Event(type="NUMPAD", field=field, txn_index=txn, digits=digits)))
        elif key == "*":
            self.keyed = None
            await self._play(self.last_audio)
        else:
            if len(self.keyed) < MAX_KEYED_DIGITS:
                self.keyed += key
            await self._resume()

    def _numeric_field(self) -> tuple[str, int | None] | None:
        s = self.s
        if s.state in ("GAP_FILL", "READBACK") and s.current_field in KEYPAD_FIELDS:
            return s.current_field, s.current_txn
        return None

    def _begin_entry(self, field: str, txn: int | None) -> None:
        self.keyed, self.entry_field = "", (field, txn)

    async def _resume(self) -> None:
        """Nothing to say after this key. If it stopped the audio, listen again now."""
        if self.playing_mark:
            await self._play(b"")
        else:
            self.listening = True

    # ---- after each FSM step
    async def _apply(self, s: Session, acts: list[Action]) -> None:
        routes_caller.commit(s, acts)
        self.s = s
        for a in acts:
            field = a.data.get("field")
            if a.type == "ShowNumpad" and field in KEYPAD_FIELDS:
                self._begin_entry(field, a.data.get("txn_index"))
        segments = [(a.text or "", a.speed) for a in acts if a.type == "SpeakPrompt" and a.text]
        if s.state in TERMINAL:
            self.ending = True
            self.keyed = None
            if s.packet_id:
                ref = " ".join(s.packet_id.rsplit("-", 1)[-1])
                segments.append((prompts.text("REFERENCE", s.lang, s.channel, ref=ref), "readback"))
        await self._speak(segments)

    async def _speak_id(self, prompt_id: str) -> None:
        await self._speak([(prompts.text(prompt_id, self.s.lang, self.s.channel), "prompt")])

    async def _speak(self, segments: Sequence[tuple[str, str]]) -> None:
        if not segments:  # keep the last audio for the repeat key
            await self._resume()
            return
        settings = get_settings()
        lang: tts.Lang = "ta-IN" if self.s.lang == "ta" else "en-IN"
        out = bytearray()
        try:
            for i, (text, speed) in enumerate(segments):
                rate = settings.TTS_SPEED_READBACK if speed == "readback" else settings.TTS_SPEED_PROMPT
                data, _ = await tts.synthesize(
                    text, lang=lang, speed=rate, telephony=True,
                    request_id=f"{self.s.id}-{self.s.api_turns}-p{i}",
                    persist=prompts.is_static_text(text, self.s.lang))
                out += to_phone_audio(data)
        except GnaniError as e:
            log(logger, "phone tts failed", code=e.code, status=e.status, call=self.call_ref)
            await self._voice_lost()
            return
        self.last_audio = bytes(out)
        await self._play(self.last_audio)

    async def _voice_lost(self) -> None:
        """Without TTS the caller hears nothing, so end the call. TwiML then tells them to call 1930."""
        if self.s.state not in TERMINAL:
            s, acts = next_state(self.s, Event(type="HUMAN"))
            routes_caller.commit(s, acts)
            self.s = s
        self.ending = True
        self.inbox.put_nowait(("close", None))

    async def _play(self, data: bytes) -> None:
        self.listening = False
        for i in range(0, len(data), CHUNK_BYTES):
            payload = base64.b64encode(data[i:i + CHUNK_BYTES]).decode()
            await self.send(json.dumps({"event": "media", "streamSid": self.stream_sid, "media": {"payload": payload}}))
        self.marks += 1
        self.playing_mark = f"m{self.marks}"
        await self.send(json.dumps({"event": "mark", "streamSid": self.stream_sid, "mark": {"name": self.playing_mark}}))

    def _caller_left(self) -> None:
        """A caller who hangs up mid-call still gets a packet if they told us anything: a person follows it up."""
        s = self.s
        captured = s.transcripts or s.txns or any(f.value is not None for f in s.fields.values())
        if s.state in TERMINAL:
            pass
        elif captured:
            routes_caller.commit(*next_state(s, Event(type="HUMAN", text="hangup")))
        else:
            routes_caller.SESSIONS.pop(s.id, None)
        log(logger, "phone call ended", call=self.call_ref, state=s.state)

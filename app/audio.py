"""Audio normalisation via ffmpeg, entirely in memory (stdin -> stdout pipes, no temp files)."""

import asyncio
import io
import shutil
import subprocess
import wave

import numpy as np


class AudioError(Exception):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


async def normalize(raw: bytes, max_s: float | None = None) -> bytes:
    """Any browser format (webm/ogg/mp4/wav) -> 16 kHz mono 16-bit WAV bytes.

    The input is untrusted, so:
    - `-protocol_whitelist pipe` stops playlist/concat inputs (m3u8, ffconcat) from opening local files or URLs;
    - `-t` caps the decoded duration, so a tiny file that claims hours of audio cannot exhaust memory;
    - the process is killed after FFMPEG_TIMEOUT_S.
    """
    from app.config import get_settings

    if not raw:
        raise AudioError("empty audio")
    s = get_settings()
    cap = (max_s if max_s is not None else s.MAX_TURN_S) + 1
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
           "-protocol_whitelist", "pipe", "-i", "pipe:0",
           "-t", f"{cap:.1f}", "-vn", "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", "-f", "wav", "pipe:1"]
    # A thread, not asyncio.create_subprocess_exec: uvicorn --reload on Windows runs a selector loop,
    # which cannot spawn subprocesses (NotImplementedError). subprocess.run kills the process on timeout.
    try:
        proc = await asyncio.to_thread(subprocess.run, cmd, input=raw, capture_output=True,
                                       timeout=s.FFMPEG_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        raise AudioError("ffmpeg timeout") from None
    if proc.returncode != 0 or not proc.stdout:
        raise AudioError(f"ffmpeg failed: {proc.stderr.decode(errors='ignore')[:200]}")
    return fix_wav_header(proc.stdout)


def fix_wav_header(data: bytes) -> bytes:
    """ffmpeg writing WAV to a pipe leaves size fields unset; rewrite a clean header."""
    pcm = _pcm_from_wav(data)
    return pcm_to_wav(pcm, 16000)


def _pcm_from_wav(data: bytes) -> bytes:
    idx = data.find(b"data")
    if idx < 0:
        raise AudioError("no data chunk")
    return data[idx + 8:]


def pcm_to_wav(pcm: bytes, rate: int, channels: int = 1, width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def duration_s(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def split_wav(wav_bytes: bytes, max_s: float) -> list[bytes]:
    """Split a WAV into consecutive pieces of at most max_s seconds (used by bench for long clips)."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        frames = w.readframes(w.getnframes())
    step = int(max_s * rate) * ch * width
    return [pcm_to_wav(frames[i:i + step], rate, ch, width) for i in range(0, len(frames), step)]


def split_at_quiet(wav_bytes: bytes, max_s: float, search_s: float = 5.0, hop_s: float = 0.02) -> list[bytes]:
    """Split a 16-bit mono WAV into pieces of at most max_s, cutting at the quietest moment before each limit.

    Prisma takes 30 s per request, so a long turn goes in pieces. Cutting in a pause keeps a spoken number whole.
    """
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        rate = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    window, search, hop = int(max_s * rate), int(min(search_s, max_s / 2) * rate), max(1, int(hop_s * rate))
    if len(pcm) <= window:
        return [wav_bytes]
    pieces, start = [], 0
    while len(pcm) - start > window:
        end = start + window
        zone = pcm[end - search:end].astype(np.float64)
        frames = len(zone) // hop
        energy = (zone[:frames * hop] ** 2).reshape(frames, hop).sum(axis=1)
        cut = end - search + int(np.argmin(energy)) * hop + hop // 2
        pieces.append(pcm_to_wav(pcm[start:cut].tobytes(), rate))
        start = cut
    pieces.append(pcm_to_wav(pcm[start:].tobytes(), rate))
    return pieces

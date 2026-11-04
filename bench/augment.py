"""Create benchmark conditions from acted clean clips.

Conditions: clean, snr10, snr5 (recorded street noise mixed by RMS), tel8k (300–3400 Hz band-pass,
8 kHz µ-law round trip, back to 16 kHz), snr10_tel8k.

    python bench/augment.py [--conditions clean,snr10,...]
Inputs : bench/corpus/<clip_id>.<ext>, bench/noise/*.wav
Outputs: bench/augmented/<condition>/<clip_id>.wav (16 kHz mono)
"""

import argparse
import io
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
EXTS = (".wav", ".m4a", ".mp3", ".ogg", ".webm", ".flac")
CONDITIONS = ["clean", "snr10", "snr5", "tel8k", "snr10_tel8k"]


def ffmpeg(data: bytes, *args: str) -> bytes:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", *args, "pipe:1"],
                       input=data, capture_output=True, check=True)
    return p.stdout


def to_pcm16k(data: bytes) -> np.ndarray:
    raw = ffmpeg(data, "-ac", "1", "-ar", "16000", "-f", "s16le")
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def write_wav(path: Path, x: np.ndarray, rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def wav_bytes(x: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x ** 2)) + 1e-12)


def mix_snr(speech: np.ndarray, noise: np.ndarray, snr_db: float, rng: np.random.Generator) -> np.ndarray:
    if len(noise) < len(speech):
        noise = np.tile(noise, int(np.ceil(len(speech) / len(noise))))
    start = int(rng.integers(0, len(noise) - len(speech) + 1))
    n = noise[start:start + len(speech)]
    gain = rms(speech) / (rms(n) * (10 ** (snr_db / 20)))
    out = speech + gain * n
    peak = np.max(np.abs(out))
    return out / peak * 0.98 if peak > 1 else out


def telephone(x: np.ndarray) -> np.ndarray:
    data = ffmpeg(wav_bytes(x), "-af", "highpass=f=300,lowpass=f=3400", "-ar", "8000", "-acodec", "pcm_mulaw",
                  "-f", "wav")
    return to_pcm16k(data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conditions", default=",".join(CONDITIONS))
    ap.add_argument("--seed", type=int, default=1930)
    ap.add_argument("--corpus", default=str(ROOT / "corpus"), help="folder of clean clips (e.g. bench/corpus/probe)")
    a = ap.parse_args()
    conds = a.conditions.split(",")
    rng = np.random.default_rng(a.seed)
    clips = sorted(p for p in Path(a.corpus).iterdir() if p.suffix in EXTS and p.stem != "smoke")
    noises = [to_pcm16k(p.read_bytes()) for p in sorted((ROOT / "noise").glob("*.wav"))] \
        if (ROOT / "noise").exists() else []
    if any(c.startswith("snr") for c in conds) and not noises:
        print("No noise files in bench/noise/ — skipping SNR conditions.")
        conds = [c for c in conds if not c.startswith("snr")]
    for clip in clips:
        x = to_pcm16k(clip.read_bytes())
        for c in conds:
            y = x
            if c.startswith("snr"):
                snr = float(c.split("_")[0][3:])
                y = mix_snr(x, noises[int(rng.integers(0, len(noises)))], snr, rng)
            if c.endswith("tel8k"):
                y = telephone(y)
            write_wav(ROOT / "augmented" / c / f"{clip.stem}.wav", y)
        print(f"{clip.stem}: {', '.join(conds)}")
    print(f"{len(clips)} clips × {len(conds)} conditions written to bench/augmented/")
    return 0


if __name__ == "__main__":
    sys.exit(main())

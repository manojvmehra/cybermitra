"""Day-1 smoke test: exactly 1 STT call + 1 TTS call. Prints response shape and latency.

    python scripts/smoke_gnani.py [--clip bench/corpus/smoke.wav]
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app import audio  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.logging_utils import mask  # noqa: E402


async def main(clip: Path) -> int:
    s = get_settings()
    if not s.GNANI_API_KEY:
        print("GNANI_API_KEY missing — copy .env.example to .env and fill it.")
        return 2
    if not clip.exists():
        print(f"Missing {clip}. Record a short acted Tamil clip (synthetic numbers only).")
        return 2
    wav = await audio.normalize(clip.read_bytes())
    headers = {"X-API-Key-ID": s.GNANI_API_KEY, "X-API-Request-ID": "smoke-1"}
    async with httpx.AsyncClient(base_url=s.GNANI_BASE_URL, timeout=s.GNANI_TIMEOUT_S) as c:
        t0 = time.perf_counter()
        r = await c.post("/stt/v3", headers=headers, files={"audio_file": ("smoke.wav", wav, "audio/wav")},
                         data={"language_code": "ta-IN", "format": "transcribe"})
        dt = (time.perf_counter() - t0) * 1000
        print(f"STT status={r.status_code} latency={dt:.0f} ms")
        try:
            body = r.json()
            shape = {k: (type(v).__name__ if k not in ("transcript", "output") else "…") for k, v in body.items()}
            print("STT response keys/types:", json.dumps(shape))
            print("STT transcript (masked):", mask(body.get("transcript", "")))
            print("STT output.literal (masked):", mask((body.get("output") or {}).get("literal", "")))
        except ValueError:
            print(r.text[:300])
        stt_ok = r.status_code == 200

        t0 = time.perf_counter()
        r2 = await c.post("/api/v1/tts/inference", headers={**headers, "X-API-Request-ID": "smoke-2"}, json={
            "text": "வணக்கம். இது ஒரு சோதனை.", "voice": s.TTS_VOICE_TA, "model": s.TTS_MODEL, "language": "ta-IN",
            "speed": 1.0, "audio_config": {"sample_rate": s.TTS_SAMPLE_RATE, "num_channels": 1, "sample_width": 2,
                                           "encoding": "linear_pcm", "container": "wav"}})
        dt = (time.perf_counter() - t0) * 1000
        print(f"TTS status={r2.status_code} latency={dt:.0f} ms bytes={len(r2.content)} "
              f"content-type={r2.headers.get('content-type')}")
        if r2.status_code != 200:
            print(r2.text[:300])
        else:
            out = Path(".cache/smoke_tts.wav")
            out.parent.mkdir(exist_ok=True)
            out.write_bytes(r2.content)
            print(f"TTS audio written to {out}")
        tts_ok = r2.status_code == 200
    print("\nNow check credit usage on the Gnani dashboard for these 2 calls.")
    if not (stt_ok and tts_ok):
        print("STOP: a call failed — fix before continuing.")
        return 1
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", type=Path, default=Path("bench/corpus/smoke.wav"))
    sys.exit(asyncio.run(main(ap.parse_args().clip)))

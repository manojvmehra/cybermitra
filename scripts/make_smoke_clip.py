"""Generate a synthetic Tamil smoke-test clip with Timbre (1 TTS call; cached afterwards).

    python scripts/make_smoke_clip.py
Writes bench/corpus/smoke.wav. All numbers are fake: amount 50,000, phone 98765 43218.
This is TTS speech, not an acted human clip: fine for the smoke test, NOT for the benchmark corpus.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.gnani import http, tts  # noqa: E402

TEXT = ("நேத்து எஸ்பிஐ பேங்க்ல இருந்து பேசுறோம்னு ஒரு கால் வந்துச்சு. ஓடிபி கேட்டாங்க. "
        "ஐம்பதாயிரம் ரூபாய் போச்சு. அந்த நம்பர் ஒன்பது, எட்டு, ஏழு, ஆறு, ஐந்து, "
        "நான்கு, மூன்று, இரண்டு, ஒன்று, எட்டு.")
TRUTH = {"amount": 50000, "suspect_phone": "9876543218", "bank": "SBI"}


async def main() -> int:
    data, key = await tts.synthesize(TEXT, lang="ta-IN", speed=1.0, request_id="make-smoke")
    out = Path("bench/corpus/smoke.wav")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"Wrote {out} ({len(data)} bytes). Truth: {TRUTH}")
    await http.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

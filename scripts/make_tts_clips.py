"""Generate SYNTHETIC (Timbre TTS) probe clips into bench/corpus/probe/ and upsert their manifest rows.

    python scripts/make_tts_clips.py [--yes]

All numbers are fake. These clips are clean machine speech: use them to choose STT settings and to find
lexicon gaps, never as the reported benchmark (that needs acted human clips). Manifest rows carry
"synthetic_tts": true so reports can separate them.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import cache  # noqa: E402
from app.gnani import http, tts  # noqa: E402

D = ["பூஜ்ஜியம்", "ஒன்று", "இரண்டு", "மூன்று", "நான்கு", "ஐந்து", "ஆறு", "ஏழு", "எட்டு", "ஒன்பது"]


def ta(digits: str, groups: tuple[int, ...]) -> str:
    """Tamil digit words, comma between groups (how a person reads a number off a screen)."""
    out, i = [], 0
    for g in groups:
        out.append(" ".join(D[int(c)] for c in digits[i:i + g]))
        i += g
    return ", ".join(out)


CLIPS = [
    {"clip_id": "tts_s1_otp", "voice": "Asmita", "script_id": "S1_OTP_BANK",
     "truth": {"amount": 50000, "suspect_phone": "9876543218", "utr": "430619827418", "bank": "SBI"},
     "text": "எஸ்பிஐ பேங்க்ல இருந்து KYC update பண்ணணும்னு கால் வந்துச்சு. ஓடிபி சொன்னேன். "
             "ஐம்பதாயிரம் ரூபாய் போச்சு. நம்பர் {phone}. UTR {utr}."},
    {"clip_id": "tts_s2_upi", "voice": "Trisha", "script_id": "S2_UPI_COLLECT",
     "truth": {"amount": 25000, "suspect_phone": "9123456780", "utr": "512300004567", "bank": "HDFC"},
     "text": "OLX-ல ஒருத்தர் collect request அனுப்பினார். பின் போட்டேன். HDFC அக்கவுண்ட்ல இருந்து "
             "இருபத்தைந்தாயிரம் ரூபாய் கட் ஆச்சு. அவர் நம்பர் {phone}. UTR {utr}."},
    {"clip_id": "tts_s3_arrest", "voice": "Brinda", "script_id": "S3_DIGITAL_ARREST",
     "truth": {"amount": 225000, "suspect_phone": "8000012345", "utr": "600011112222", "bank": "Indian Bank"},
     "text": "CBI-ல இருந்து வீடியோ கால் பண்ணாங்க, பார்சல்ல drugs இருக்குன்னு மிரட்டினாங்க. இந்தியன் பேங்க்ல இருந்து "
             "இரண்டு லட்சத்து இருபத்தைந்தாயிரம் ரூபாய் அனுப்பினேன். நம்பர் எட்டு, டபுள் பூஜ்ஜியம், டபுள் பூஜ்ஜியம், "
             "ஒன்று இரண்டு மூன்று நான்கு ஐந்து. UTR {utr}."},
    {"clip_id": "tts_s4_invest", "voice": "Vedika", "script_id": "S4_INVESTMENT",
     "truth": {"amount": 150000, "suspect_phone": "7000098765", "utr": "123400005678", "bank": "ICICI"},
     "text": "Telegram trading group-ல profit டபுள் ஆகும்னு சொன்னாங்க. ICICI அக்கவுண்ட்ல இருந்து ஒன்றரை லட்சம் "
             "invest பண்ணேன். அவங்க நம்பர் {phone}. UTR {utr}."},
    {"clip_id": "tts_s5_job", "voice": "Noopur", "script_id": "S5_JOB_TASK",
     "truth": {"amount": 49999, "suspect_phone": "6000011122", "utr": "998877660011", "bank": "Canara Bank"},
     "text": "YouTube like பண்ணா பணம் தருவோம்னு part time job. கனரா பேங்க்ல இருந்து நாற்பத்தொன்பதாயிரத்து "
             "தொள்ளாயிரத்து தொண்ணூற்றொன்பது ரூபாய் போச்சு. நம்பர் {phone}. UTR {utr}."},
    {"clip_id": "tts_s6_loan", "voice": "Asmita", "script_id": "S6_LOAN_APP",
     "truth": {"amount": 12500, "suspect_phone": "9988776655", "utr": "100020003000", "bank": "Axis Bank"},
     "text": "Loan app-ல processing fee-னு Axis பேங்க்ல இருந்து பன்னிரண்டாயிரத்து ஐநூறு ரூபாய் கட்டினேன். "
             "நம்பர் {phone}. UTR {utr}."},
    {"clip_id": "tts_s7_care", "voice": "Trisha", "script_id": "S7_FAKE_CARE",
     "truth": {"amount": 100500, "suspect_phone": "9000090000", "utr": "777788889999", "bank": "Kotak"},
     "text": "Google-ல customer care நம்பர் தேடி கால் பண்ணேன். AnyDesk install பண்ண சொன்னாங்க. கோட்டக் "
             "அக்கவுண்ட்ல இருந்து ஒரு லட்சத்து ஐநூறு ரூபாய் போச்சு. நம்பர் {phone}. UTR {utr}."},
    {"clip_id": "tts_s1_codemix", "voice": "Vedika", "script_id": "S1_OTP_BANK",
     "truth": {"amount": 50000, "suspect_phone": "9876543218", "utr": "430619827418", "bank": "SBI"},
     "text": "SBI bank-ல இருந்து கால் வந்துச்சு. fifty thousand rupees போச்சு. நம்பர் nine eight seven six five, "
             "four three two one eight. UTR four three zero six, one nine eight two, seven four one eight."},
]


def render(c: dict) -> str:  # type: ignore[type-arg]
    t = c["truth"]
    return c["text"].format(phone=ta(t["suspect_phone"], (5, 5)), utr=ta(t["utr"], (4, 4, 4)))


async def main(yes: bool) -> int:
    todo = [c for c in CLIPS if cache.get_wav(tts.tts_key(render(c), "ta-IN", 1.0, c["voice"])) is None]
    print(f"{len(CLIPS)} clips, {len(todo)} need a TTS call.")
    if todo and not yes and input("Proceed? [y/N] ").strip().lower() != "y":
        return 1
    out_dir = Path("bench/corpus/probe")
    out_dir.mkdir(parents=True, exist_ok=True)
    for c in CLIPS:
        data, _ = await tts.synthesize(render(c), lang="ta-IN", speed=1.0, voice=c["voice"],
                                       request_id=f"clip-{c['clip_id']}")
        (out_dir / f"{c['clip_id']}.wav").write_bytes(data)
        print(f"  {c['clip_id']} ({c['voice']}) {len(data)} bytes")
    await http.aclose()

    manifest = Path("bench/manifest.jsonl")
    rows = [json.loads(x) for x in manifest.read_text(encoding="utf-8").splitlines() if x.strip()]
    ids = {c["clip_id"] for c in CLIPS}
    rows = [r for r in rows if r["clip_id"] not in ids]
    rows += [{"clip_id": c["clip_id"], "script_id": c["script_id"], "speaker": f"tts-{c['voice']}",
              "synthetic_tts": True, "field_truth": c["truth"]} for c in CLIPS]
    manifest.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"Manifest updated ({len(CLIPS)} synthetic rows).")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true")
    sys.exit(asyncio.run(main(ap.parse_args().yes)))

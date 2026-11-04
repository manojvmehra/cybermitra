"""Render every static prompt (both languages) into the TTS cache so live sessions hit cache.

    python scripts/prerender_prompts.py [--yes]
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import cache  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.dialog import prompts  # noqa: E402
from app.gnani import tts  # noqa: E402


async def main(yes: bool) -> int:
    s = get_settings()
    jobs = []
    for pid in prompts.STATIC_PROMPT_IDS:
        for lang, code in (("ta", "ta-IN"), ("en", "en-IN")):
            text = prompts.text(pid, lang)
            if cache.get_wav(tts.tts_key(text, code, s.TTS_SPEED_PROMPT)) is None:  # type: ignore[arg-type]
                jobs.append((pid, code, text))
    print(f"{len(jobs)} prompts to render ({len(prompts.STATIC_PROMPT_IDS) * 2 - len(jobs)} already cached).")
    if not jobs:
        return 0
    if len(jobs) > 50:
        print("More than 50 TTS calls — needs explicit approval.")
    if not yes and input("Proceed? [y/N] ").strip().lower() != "y":
        return 1
    for pid, code, text in jobs:
        await tts.synthesize(text, lang=code, speed=s.TTS_SPEED_PROMPT)  # type: ignore[arg-type]
        print(f"  {pid} {code} ok")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true")
    sys.exit(asyncio.run(main(ap.parse_args().yes)))

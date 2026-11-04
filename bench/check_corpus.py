"""Check the recordings before spending any API calls. Makes no network calls.

    python bench/check_corpus.py [--min-speakers 3]

Reports manifest mistakes, clips still to record, files nobody references, clips Prisma would refuse, the
§10 coverage rules (speakers per script, one improvised script per speaker) and whether noise files exist.
Exit code 0 means the corpus is ready to run.
"""

import argparse
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bench.augment import CONDITIONS, EXTS, clip_files  # noqa: E402
from bench.corpus_lib import load_calls, manifest_problems  # noqa: E402

ROOT = Path(__file__).resolve().parent
MAX_S = 30.0  # Prisma REST limit


def seconds(path: Path) -> float | None:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=False)
    try:
        return float(p.stdout.strip())
    except ValueError:
        return None


def main(min_speakers: int = 3) -> int:
    calls = [c for c in load_calls(ROOT / "manifest.jsonl") if not c.synthetic_tts]
    problems = manifest_problems(calls)
    files = {p.stem: p for p in clip_files(ROOT / "corpus")} if (ROOT / "corpus").exists() else {}
    listed = {t["clip_id"]: c for c in calls for t in c.turns}
    missing = sorted(set(listed) - set(files))
    print(f"{len(calls)} acted calls, {len(listed)} clips listed, {len(files)} audio files in bench/corpus/")
    if missing:
        print(f"Still to record: {len(missing)}")
        for cid in missing[:20]:
            print(f"  {cid}")
        if len(missing) > 20:
            print(f"  … and {len(missing) - 20} more")
    extra = sorted(set(files) - set(listed))
    for cid in extra:
        problems.append(f"{files[cid].name}: not in the manifest, so it would never be scored")
    for path in files.values():
        dur = seconds(path)
        if dur is None:
            problems.append(f"{path.name}: unreadable audio")
        elif dur > MAX_S:
            problems.append(f"{path.name}: {dur:.0f} s is over Prisma's {MAX_S:.0f} s limit")

    per_script: dict[str, set[str]] = defaultdict(set)
    improvised = {c.speaker for c in calls if c.improvised}
    for c in calls:
        if c.narrative and c.narrative["clip_id"] in files:
            per_script[c.script_id or "?"].add(str(c.speaker))
    for script in sorted({c.script_id or "?" for c in calls}):
        n = len(per_script[script])
        if n < min_speakers:
            problems.append(f"{script}: {n} speaker(s) recorded, needs {min_speakers}")
    for sp in sorted({str(c.speaker) for c in calls} - {str(x) for x in improvised}):
        problems.append(f"{sp}: no improvised script (make_manifest.py --improvised {sp}:SCRIPT)")

    noise = list((ROOT / "noise").glob("*.wav")) if (ROOT / "noise").exists() else []
    if not noise:
        snr = [c for c in CONDITIONS if c.startswith("snr")]
        problems.append(f"bench/noise/ has no .wav files, so {', '.join(snr)} would be skipped")
    if missing:
        problems.append(f"{len(missing)} clips not recorded")
    for line in problems:
        print(f"PROBLEM: {line}")
    print("READY" if not problems else f"NOT READY: {len(problems)} problem(s). Formats accepted: {', '.join(EXTS)}")
    return 0 if not problems else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-speakers", type=int, default=3)
    sys.exit(main(ap.parse_args().min_speakers))

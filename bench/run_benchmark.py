"""Run STT (cached) + rule extractor over every acted clip × condition and score fields BEFORE read-back.

    python bench/run_benchmark.py [--conditions clean,tel8k] [--yes]
Writes bench/results/run.jsonl (one row per clip×condition). bench/report.py turns it into RESULTS.md.
No numbers are hand-written anywhere: everything comes from real API output.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import cache  # noqa: E402
from app.dialog.readback import chunk  # noqa: E402
from app.gnani import http, stt  # noqa: E402
from app.gnani.http import GnaniError  # noqa: E402
from app.nlp import extractor, numbers  # noqa: E402

ROOT = Path(__file__).resolve().parent
FIELDS = ["amount", "bank", "suspect_phone", "utr"]
NUMERIC = {"amount", "suspect_phone", "utr"}


def load_manifest() -> list[dict]:  # type: ignore[type-arg]
    rows = []
    for line in (ROOT / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("//"):
            rows.append(json.loads(line))
    return rows


def oracle_readback(field: str, got: object, truth: object) -> dict:  # type: ignore[type-arg]
    """SIMULATION: a perfect user answers yes/no per chunk against truth and corrects wrong chunks.
    Reports corrections needed and whether the field would end unconfirmed (>2 repairs)."""
    if got is None:
        return {"corrections": None, "unconfirmed": None, "missing": True}
    want = chunk(field, truth)  # type: ignore[arg-type]
    have = chunk(field, got)  # type: ignore[arg-type]
    wrong = len(want) if len(want) != len(have) else sum(1 for a, b in zip(want, have, strict=True) if a != b)
    return {"corrections": wrong, "unconfirmed": wrong > 2, "missing": False}


def would_cost(stems: list[tuple[Path, str]], profile: stt.SttProfile) -> int:
    n = 0
    for p, _ in stems:
        form = stt.build_form(profile, None, None)
        key = cache.cache_key(p.read_bytes(), {"endpoint": "stt/v3", **form})
        if cache.get_json("stt", key) is None:
            n += 1
    return n


async def main(conds: list[str], yes: bool) -> int:
    profile = stt.SttProfile.from_settings()
    manifest = load_manifest()
    jobs: list[tuple[Path, str, dict]] = []  # type: ignore[type-arg]
    for row in manifest:
        for c in conds:
            p = ROOT / "augmented" / c / f"{row['clip_id']}.wav"
            if p.exists():
                jobs.append((p, c, row))
    if not jobs:
        print("No augmented clips found. Record clips into bench/corpus/ and run bench/augment.py.")
        return 2
    uncached = would_cost([(p, c) for p, c, _ in jobs], profile)
    print(f"{len(jobs)} clip×condition jobs; {uncached} need a live STT call (rest cached).")
    if uncached > 50 and not yes:
        print("More than 50 live calls — re-run with --yes after approval.")
        return 1
    if uncached and not yes and input("Proceed? [y/N] ").strip().lower() != "y":
        return 1

    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    rows_out = []
    for p, cond, row in jobs:
        truth = row["field_truth"]
        rec: dict = {"clip_id": row["clip_id"], "script_id": row.get("script_id"),  # type: ignore[type-arg]
                     "speaker": row.get("speaker"), "synthetic_tts": bool(row.get("synthetic_tts")),
                     "condition": cond, "stt_model": profile.model,
                     "stt_format": profile.format}
        try:
            r = await stt.transcribe(p.read_bytes(), profile=profile, request_id=f"bench-{row['clip_id']}-{cond}")
        except GnaniError as e:
            rec["error"] = f"{e.status} {e.code}"
            rows_out.append(rec)
            continue
        rec["latency_ms"] = r.latency_ms
        rec["cached"] = r.cached
        rec["stt"] = asdict(r)
        cands = extractor.extract_rules(r)
        fields = {}
        for f in FIELDS:
            if f not in truth:
                continue
            c = cands.get(f)
            got = c.value if c else None
            fields[f] = {
                "truth": truth[f], "got": got, "exact": got == truth[f],
                "confidence": c.confidence if c else None, "source": c.source if c else None,
                "method": c.method if c else None,
            }
            if f in NUMERIC:
                fields[f]["readback_sim"] = oracle_readback(f, got, truth[f])
        # dual-channel agreement: parse ITN transcript and literal independently
        if r.literal is not None:
            agree = {}
            for f in NUMERIC & set(truth):
                if f == "amount":
                    a, b = numbers.parse_amount(r.text).value, numbers.parse_amount(r.literal).value
                else:
                    n = 10 if f == "suspect_phone" else 12
                    a = numbers.parse_digit_string(r.text, n).value
                    b = numbers.parse_digit_string(r.literal, n).value
                agree[f] = {"itn": a, "literal": b, "agree": a is not None and a == b,
                            "itn_exact": a == truth[f], "literal_exact": b == truth[f]}
            rec["agreement"] = agree
        rec["fields"] = fields
        rows_out.append(rec)
        print(f"  {row['clip_id']} [{cond}] " + " ".join(f"{k}:{'✓' if v['exact'] else '✗'}" for k, v in fields.items()))
    with (out / "run.jsonl").open("w", encoding="utf-8") as fh:
        for r_ in rows_out:
            fh.write(json.dumps(r_, ensure_ascii=False) + "\n")
    (out / "metrics.json").write_text(json.dumps(http.metrics.snapshot(), indent=2), encoding="utf-8")
    print(f"Wrote {out / 'run.jsonl'}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--conditions", default="clean,snr10,snr5,tel8k,snr10_tel8k")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.conditions.split(","), a.yes)))

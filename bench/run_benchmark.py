"""Run STT (cached) over every clip in the manifest × condition and score fields BEFORE read-back.

    python bench/run_benchmark.py [--conditions clean,tel8k] [--yes]

Story clips go through the narrative extractor; answer clips go through the parser a live call uses for that
slot. Writes bench/results/run.jsonl (one row per clip×condition), which bench/report.py turns into RESULTS.md.
No numbers are hand-written anywhere: everything comes from real API output.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import cache  # noqa: E402
from app.dialog.readback import chunk  # noqa: E402
from app.gnani import http, stt  # noqa: E402
from app.gnani.http import GnaniError  # noqa: E402
from app.gnani.stt import SttResult  # noqa: E402
from app.nlp import extractor, numbers  # noqa: E402
from bench.corpus_lib import NUMERIC_SLOTS, Call, load_calls, manifest_problems, score_slot  # noqa: E402

ROOT = Path(__file__).resolve().parent
FIELDS = ["amount", "bank", "suspect_phone", "utr"]
NUMERIC = {"amount", "suspect_phone", "utr"}
DIGIT_LEN = {"suspect_phone": 10, "victim_mobile": 10, "utr": 12}


def oracle_readback(field: str, got: object, truth: object) -> dict[str, Any]:
    """SIMULATION: a perfect user answers yes/no per chunk against truth and corrects wrong chunks.
    Reports corrections needed and whether the field would end unconfirmed (>2 repairs)."""
    if got is None:
        return {"corrections": None, "unconfirmed": None, "missing": True}
    want = chunk(field, truth)  # type: ignore[arg-type]
    have = chunk(field, got)  # type: ignore[arg-type]
    wrong = len(want) if len(want) != len(have) else sum(1 for a, b in zip(want, have, strict=True) if a != b)
    return {"corrections": wrong, "unconfirmed": wrong > 2, "missing": False}


def would_cost(paths: list[Path], profile: stt.SttProfile) -> int:
    n = 0
    for p in paths:
        form = stt.build_form(profile, None, None)
        key = cache.cache_key(p.read_bytes(), {"endpoint": "stt/v3", **form})
        if cache.get_json("stt", key) is None:
            n += 1
    return n


def agreement(field: str, r: SttResult, truth: Any) -> dict[str, Any]:
    """Dual channel: parse the ITN transcript and the literal independently."""
    assert r.literal is not None
    if field == "amount":
        a, b = numbers.parse_amount(r.text).value, numbers.parse_amount(r.literal).value
    else:
        n = DIGIT_LEN[field]
        a, b = numbers.parse_digit_string(r.text, n).value, numbers.parse_digit_string(r.literal, n).value
    return {"itn": a, "literal": b, "agree": a is not None and a == b, "itn_exact": a == truth,
            "literal_exact": b == truth}


def score_narrative(r: SttResult, truth: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    cands = extractor.extract_rules(r)
    fields: dict[str, Any] = {}
    for f in FIELDS:
        if f not in truth:
            continue
        c = cands.get(f)
        got = c.value if c else None
        fields[f] = {"truth": truth[f], "got": got, "exact": got == truth[f], "confidence": c.confidence if c else None,
                     "source": c.source if c else None, "method": c.method if c else None}
        if f in NUMERIC:
            fields[f]["readback_sim"] = oracle_readback(f, got, truth[f])
    if "amounts" in truth:  # a story with several debits: every one must be heard
        got_all = sorted(c.value for k, c in cands.items() if k == "amount" or k.startswith("amount."))
        fields["all amounts in story"] = {"truth": truth["amounts"], "got": got_all,
                                          "exact": got_all == sorted(truth["amounts"])}
    agree = {f: agreement(f, r, truth[f]) for f in NUMERIC & set(truth)} if r.literal is not None else {}
    return fields, agree


def score_turn(call: Call, turn: dict[str, Any], r: SttResult) -> tuple[dict[str, Any], dict[str, Any]]:
    slot, truth = turn["slot"], turn.get("truth")
    if slot == "narrative":
        return score_narrative(r, truth or {})
    row = score_slot(slot, truth, r.text, r.literal, call.reference_time)
    agree: dict[str, Any] = {}
    if slot in NUMERIC_SLOTS:
        row["readback_sim"] = oracle_readback(slot, row["got"], truth)
        if r.literal is not None:
            agree[f"{slot} (answer)"] = agreement(slot, r, truth)
    return {f"{slot} (answer)": row}, agree


def jobs_for(calls: list[Call], conds: list[str]) -> tuple[list[tuple[Path, str, Call, dict[str, Any]]], int]:
    """-> (clips found on disk, clips listed in the manifest but not found)."""
    jobs, missing = [], 0
    for call in calls:
        for turn in call.turns:
            for c in conds:
                p = ROOT / "augmented" / c / f"{turn['clip_id']}.wav"
                if p.exists():
                    jobs.append((p, c, call, turn))
                elif c == "clean":
                    missing += 1
    return jobs, missing


async def main(conds: list[str], yes: bool) -> int:
    profile = stt.SttProfile.from_settings()
    calls = load_calls(ROOT / "manifest.jsonl")
    problems = manifest_problems(calls)
    if problems:
        print("Fix bench/manifest.jsonl first:\n  " + "\n  ".join(problems))
        return 2
    jobs, missing = jobs_for(calls, conds)
    if not jobs:
        print("No augmented clips found. Record clips into bench/corpus/ and run bench/augment.py.")
        return 2
    if missing:
        print(f"Note: {missing} manifest clips have no recording yet (bench/check_corpus.py lists them).")
    uncached = would_cost([p for p, *_ in jobs], profile)
    print(f"{len(jobs)} clip×condition jobs; {uncached} need a live STT call (rest cached).")
    if uncached > 50 and not yes:
        print("More than 50 live calls — re-run with --yes after approval.")
        return 1
    if uncached and not yes and input("Proceed? [y/N] ").strip().lower() != "y":
        return 1

    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    rows_out = []
    for p, cond, call, turn in jobs:
        rec: dict[str, Any] = {"clip_id": turn["clip_id"], "call_id": call.call_id, "slot": turn["slot"],
                               "script_id": call.script_id, "speaker": call.speaker,
                               "synthetic_tts": call.synthetic_tts, "improvised": call.improvised,
                               "condition": cond, "stt_model": profile.model, "stt_format": profile.format}
        try:
            r = await stt.transcribe(p.read_bytes(), profile=profile, request_id=f"bench-{turn['clip_id']}-{cond}")
        except GnaniError as e:
            rec["error"] = f"{e.status} {e.code}"
            rows_out.append(rec)
            continue
        rec.update(latency_ms=r.latency_ms, cached=r.cached, stt=asdict(r))
        rec["fields"], agree = score_turn(call, turn, r)
        if agree:
            rec["agreement"] = agree
        rows_out.append(rec)
        marks = " ".join(f"{k}:{'✓' if v['exact'] else '✗'}" for k, v in rec["fields"].items())
        print(f"  {turn['clip_id']} [{cond}] {marks}")
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

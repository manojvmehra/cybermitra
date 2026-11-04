"""Write bench/manifest.jsonl rows for the acted corpus, so nobody types ground truth by hand.

    python bench/make_manifest.py --speakers spk1,spk2,spk3 [--improvised spk1:S2_UPI_COLLECT] [--all-slots]

One row per script × speaker. Clips are named <script>_<speaker>_<slot>.wav, for example s1_spk2_utr_1.wav.
Rows for the named speakers are replaced; every other row (such as the TTS clips) is kept. All details are fake.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REFERENCE_TIME = "2026-11-05T12:00"  # the pretend moment of the call: "nethu" means 04-11-2026

# say = how to speak the time on the time clip. tests/test_bench_pipeline.py parses each one at REFERENCE_TIME.
SCRIPTS: dict[str, dict[str, Any]] = {
    "S1_OTP_BANK": {"short": "s1", "victim_bank": "SBI", "suspect_phone": "9876543218", "txns": [
        {"amount": 40000, "utr": "430619827418", "datetime": "04-11-2026 15:00", "say": "nethu madhiyam moonu mani"},
        {"amount": 10000, "utr": "430619827419", "datetime": "04-11-2026 16:00", "say": "nethu madhiyam naalu mani"}]},
    "S2_UPI_COLLECT": {"short": "s2", "victim_bank": "HDFC", "suspect_phone": "9123456780", "txns": [
        {"amount": 25000, "utr": "512300004567", "datetime": "05-11-2026 10:00", "say": "innaikku kaalaila pathu mani"}]},
    "S3_DIGITAL_ARREST": {"short": "s3", "victim_bank": "Indian Bank", "suspect_phone": "8000012345", "txns": [
        {"amount": 100000, "utr": "600011112222", "datetime": "04-11-2026 11:00", "say": "nethu kaalaila pathinonnu mani"},
        {"amount": 75000, "utr": "600011112223", "datetime": "04-11-2026 12:00", "say": "nethu madhiyam pannendu mani"},
        {"amount": 50000, "utr": "600011112224", "datetime": "04-11-2026 13:00", "say": "nethu madhiyam oru mani"}]},
    "S4_INVESTMENT": {"short": "s4", "victim_bank": "ICICI", "suspect_phone": "7000098765", "txns": [
        {"amount": 150000, "utr": "123400005678", "datetime": "04-11-2026 18:00", "say": "nethu saayangaalam"}]},
    "S5_JOB_TASK": {"short": "s5", "victim_bank": "Canara Bank", "suspect_phone": "6000011122", "txns": [
        {"amount": 49999, "utr": "998877660011", "datetime": "05-11-2026 09:00", "say": "innaikku kaalaila"}]},
    "S6_LOAN_APP": {"short": "s6", "victim_bank": "Axis Bank", "suspect_phone": "9988776655", "txns": [
        {"amount": 12500, "utr": "100020003000", "datetime": "04-11-2026 21:00", "say": "nethu raathiri"}]},
    "S7_FAKE_CARE": {"short": "s7", "victim_bank": "Kotak", "suspect_phone": "9000090000", "txns": [
        {"amount": 100500, "utr": "777788889999", "datetime": "05-11-2026 11:00", "say": "oru mani neram munnadi"}]},
    "S8_SEXTORTION_HANDOFF": {"short": "s8", "handoff": "HANDOFF_NONFIN", "txns": []},
}
CASE_DEFAULTS = {"payment_mode": "UPI", "district": "Madurai", "victim_name": "Test Kumar",
                 "victim_mobile": "9000000001", "called_bank": "no"}
EXTRA_SLOTS = ["payment_mode", "district", "victim_name", "victim_mobile", "called_bank"]


def build_call(script_id: str, speaker: str, improvised: bool, all_slots: bool) -> dict[str, Any]:
    sc = SCRIPTS[script_id]
    pre = f"{sc['short']}_{speaker}"
    turn = lambda name, slot, truth, **kw: {"clip_id": f"{pre}_{name}", "slot": slot, "truth": truth, **kw}  # noqa: E731
    txns = sc["txns"]
    story: dict[str, Any] = {"handoff": sc["handoff"]} if "handoff" in sc else {"bank": sc["victim_bank"]}
    if len(txns) == 1:
        story["amount"] = txns[0]["amount"]
    elif txns:
        story["amounts"] = [t["amount"] for t in txns]
    turns = [turn("narrative", "narrative", story)]
    call_truth: dict[str, Any] = {k: sc[k] for k in ("handoff",) if k in sc}
    if txns:
        for i, t in enumerate(txns):
            n = i + 1
            turns += [turn(f"amount_{n}", "amount", t["amount"], txn=i),
                      turn(f"time_{n}", "datetime", t["datetime"], txn=i),
                      turn(f"utr_{n}", "utr", t["utr"], txn=i)]
        turns += [turn("bank", "victim_bank", sc["victim_bank"]), turn("phone", "suspect_phone", sc["suspect_phone"]),
                  turn("yes", "yes", "YES"), turn("no", "no", "NO"),
                  turn("correction", "correction", {"intent": "CORRECTION", "digits": "8"})]
        if all_slots:
            turns += [turn(f, f, CASE_DEFAULTS[f]) for f in EXTRA_SLOTS]
        call_truth.update(txns=[{k: t[k] for k in ("amount", "utr", "datetime")} for t in txns],
                          victim_bank=sc["victim_bank"], suspect_phone=sc["suspect_phone"], **CASE_DEFAULTS)
    return {"call_id": pre, "script_id": script_id, "speaker": speaker, "improvised": improvised,
            "reference_time": REFERENCE_TIME, "turns": turns, "call_truth": call_truth}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--speakers", required=True, help="comma-separated, e.g. spk1,spk2,spk3")
    ap.add_argument("--improvised", default="", help="speaker:SCRIPT pairs recorded without a script")
    ap.add_argument("--all-slots", action="store_true", help="also expect clips for district, name, mobile, etc.")
    a = ap.parse_args()
    speakers = [x for x in a.speakers.split(",") if x]
    improvised = {tuple(p.split(":")) for p in a.improvised.split(",") if p}
    path = ROOT / "manifest.jsonl"
    keep = [x for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []
    keep = [x for x in keep if json.loads(x).get("speaker") not in speakers]
    rows = [build_call(sid, sp, (sp, sid) in improvised, a.all_slots) for sp in speakers for sid in SCRIPTS]
    path.write_text("\n".join(keep + [json.dumps(r, ensure_ascii=False) for r in rows]) + "\n", encoding="utf-8")
    print(f"{len(rows)} calls, {sum(len(r['turns']) for r in rows)} clips to record. Wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""SIMULATION: whole calls through the real FSM, using STT output already saved by run_benchmark.py.

    python bench/simulate_calls.py

Makes no API calls. For every clip x condition in bench/results/run.jsonl:
  1. the narrative turn is the real Prisma transcript (text + literal) of that clip;
  2. per-slot answer clips are used when the manifest lists them, in order, once each;
  3. otherwise an ORACLE caller answers: ✓/✗ per read-back chunk against ground truth (✗ then types the
     right chunk), types a missing field from the truth, skips a field with no truth, says "no more
     transactions" once the truth's transactions are in, and confirms the review.
So this measures how the dialogue behaves around real STT output; it is not a user study and it reports
no "accuracy after read-back". Writes bench/results/sim.jsonl; bench/report.py renders it.
"""

import contextlib
import json
import sys
import time
import wave
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.dialog import packet as P  # noqa: E402
from app.dialog import readback  # noqa: E402
from app.dialog.models import DIGIT_FIELDS, TXN_FIELDS, Event, Session  # noqa: E402
from app.dialog.state_machine import next_state  # noqa: E402
from app.nlp import timeparse, validators  # noqa: E402
from bench.corpus_lib import Call, load_calls, within_precision  # noqa: E402

ROOT = Path(__file__).resolve().parent
TRUTH_ALIASES = {"bank": "victim_bank"}
NUMERIC = {"amount", "utr", "suspect_phone", "victim_mobile"}
CHARS_PER_S = 13.0  # rough Timbre speaking rate, used only when no rendered prompt audio exists
MAX_STEPS = 120


def load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip() and not x.startswith("//")]


def clip_seconds(clip_id: str, condition: str) -> float | None:
    for p in (ROOT / "augmented" / condition / f"{clip_id}.wav", ROOT / "corpus" / f"{clip_id}.wav",
              ROOT / "corpus" / "probe" / f"{clip_id}.wav"):
        if p.exists():
            with wave.open(str(p), "rb") as w:
                return w.getnframes() / float(w.getframerate())
    return None


@contextlib.contextmanager
def frozen_clock(ref: datetime | None) -> Iterator[None]:
    """Make "now" the moment the caller is pretending to speak, so "nethu" means what the script meant."""
    if ref is None:
        yield
        return

    class Frozen(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> "Frozen":
            return cls(ref.year, ref.month, ref.day, ref.hour, ref.minute, tzinfo=tz)

    real = (timeparse.datetime, validators.datetime)
    timeparse.datetime = validators.datetime = Frozen  # type: ignore[misc,assignment]
    try:
        yield
    finally:
        timeparse.datetime, validators.datetime = real  # type: ignore[misc,assignment]


def truth_of(call_truth: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    """-> (per-transaction truth, case truth, expected handoff)."""
    t = dict(call_truth)
    handoff = t.pop("handoff", None)
    txns = t.pop("txns", None)
    if txns is None:
        txns = [{k: t.pop(k) for k in TXN_FIELDS if k in t}] if any(k in t for k in TXN_FIELDS) else []
    case = {TRUTH_ALIASES.get(k, k): v for k, v in t.items()}
    return txns, case, handoff


class Oracle:
    def __init__(self, txns: list[dict[str, Any]], case: dict[str, Any], stt_for_slot: Callable[[str], Any]):
        self.txns, self.case, self.stt_for_slot = txns, case, stt_for_slot
        self.corrections: dict[str, int] = {}
        self.typed: dict[str, int] = {}  # fields the voice turns never produced, so the caller typed them
        self.taps = 0

    def truth(self, field: str, txn: int | None) -> Any:
        if field in TXN_FIELDS:
            return self.txns[txn].get(field) if txn is not None and txn < len(self.txns) else None
        return self.case.get(field)

    def act(self, s: Session) -> Event | None:
        st = s.state
        if st == "READBACK" and s.readback:
            rb = s.readback
            want = self.truth(rb.field, rb.txn_index)
            if want is None:  # nothing to check against: accept, as a caller would
                return Event(type="BUTTON", field=rb.field, txn_index=rb.txn_index, chunk_index=rb.index,
                             answer="yes")
            want_chunks = readback.chunk(rb.field, want)
            if rb.field == "datetime":
                f_ = s.field("datetime", rb.txn_index)
                ok = within_precision(str(f_.value), str(want), f_.precision)
            else:
                ok = len(want_chunks) == len(rb.chunks) and want_chunks[rb.index] == rb.chunks[rb.index]
            if rb.awaiting == "correct":
                self.corrections[rb.field] = self.corrections.get(rb.field, 0) + 1
                if rb.field in DIGIT_FIELDS and len(want_chunks) == len(rb.chunks):
                    return Event(type="NUMPAD", field=rb.field, txn_index=rb.txn_index, digits=want_chunks[rb.index])
                return Event(type="NUMPAD", field=rb.field, txn_index=rb.txn_index, digits=str(want))
            return Event(type="BUTTON", field=rb.field, txn_index=rb.txn_index, chunk_index=rb.index,
                         answer="yes" if ok else "no")
        if st == "GAP_FILL" and s.current_field:
            f, txn = s.current_field, s.current_txn
            stt = self.stt_for_slot(f)
            if stt is not None:
                return Event(type="AUDIO_TURN", text=stt["text"], literal=stt.get("literal"))
            want = self.truth(f, txn)
            if want is None:
                return Event(type="SKIP", field=f, txn_index=txn)
            self.typed[f] = self.typed.get(f, 0) + 1
            return Event(type="NUMPAD", field=f, txn_index=txn, digits=str(want))
        if st == "ASK_MORE_TXN":
            return Event(type="BUTTON", field="more_txn", answer="yes" if len(s.txns) < len(self.txns) else "no")
        if st == "DUP_CHECK":
            return Event(type="BUTTON", field="dup_utr", answer="no")
        if st == "REVIEW":
            return Event(type="BUTTON", field="review", answer="yes")
        return None


def simulate(call: Call, run: dict[str, Any], runs_by_clip: dict[tuple[str, str], dict[str, Any]]
             ) -> dict[str, Any]:
    txns_t, case_t, want_handoff = truth_of(call.truth)
    cond = run["condition"]
    turn_clips: dict[str, list[str]] = {}
    for t in call.turns:
        if t["slot"] != "narrative":
            turn_clips.setdefault(t["slot"], []).append(t["clip_id"])
    used: set[str] = set()
    seconds = [clip_seconds(run["clip_id"], cond)]
    stt_ms = [run.get("latency_ms") or 0]

    def stt_for_slot(slot: str) -> dict[str, Any] | None:
        queue = turn_clips.get(slot) or []
        cid = queue.pop(0) if queue else None
        r = runs_by_clip.get((cid, cond)) if cid else None
        if cid is None or r is None or "stt" not in r:
            return None
        used.add(cid)
        seconds.append(clip_seconds(cid, cond))
        stt_ms.append(r.get("latency_ms") or 0)
        return r["stt"]

    oracle = Oracle(txns_t, case_t, stt_for_slot)
    s, acts = next_state(Session(lang="ta"), Event(type="START"))
    spoken = [a.text or "" for a in acts if a.type == "SpeakPrompt"]
    steps = 0
    with frozen_clock(call.reference_time):
        s, acts = next_state(s, Event(type="AUDIO_TURN", text=run["stt"]["text"], literal=run["stt"].get("literal")))
        spoken += [a.text or "" for a in acts if a.type == "SpeakPrompt"]
        while steps < MAX_STEPS and s.state not in ("QUEUED", "END") and not s.state.startswith("HANDOFF"):
            ev = oracle.act(s)
            if ev is None:
                break
            if ev.type in ("BUTTON", "NUMPAD", "SKIP"):
                oracle.taps += 1
            s, acts = next_state(s, ev)
            spoken += [a.text or "" for a in acts if a.type == "SpeakPrompt"]
            steps += 1

    status = "ready_for_review" if s.state == "QUEUED" else "needs_human" if s.handoff else "incomplete"
    pkt = P.build(s, status, s.handoff_reason)
    wrong_confirmed: list[str] = []
    unconfirmed: list[str] = []
    for i, t in enumerate(pkt.txns):
        for k, f in t.items():
            want = txns_t[i].get(k) if i < len(txns_t) else None
            if f.status == "unconfirmed":
                unconfirmed.append(k)
            if k in NUMERIC and f.status == "confirmed" and want is not None and f.value != want:
                wrong_confirmed.append(k)
    for k, f in pkt.fields.items():
        want = case_t.get(k)
        if f.status == "unconfirmed":
            unconfirmed.append(k)
        if k in NUMERIC and f.status == "confirmed" and want is not None and f.value != want:
            wrong_confirmed.append(k)
    tts_s = sum(len(x) for x in spoken) / CHARS_PER_S
    clip_s = sum(x for x in seconds if x is not None)
    return {
        "clip_id": run["clip_id"], "call_id": call.call_id, "condition": cond, "synthetic_tts": call.synthetic_tts,
        "final_state": s.state, "status": status, "handoff_reason": s.handoff_reason,
        "expected_handoff": want_handoff, "n_txns": len(pkt.txns), "expected_txns": len(txns_t),
        "corrections": oracle.corrections, "typed": oracle.typed, "unconfirmed": unconfirmed, "wrong_confirmed": wrong_confirmed,
        "taps": oracle.taps, "steps": steps, "voice_turns": 1 + len(used),
        "sim_seconds": {"clips": round(clip_s, 1), "stt": round(sum(stt_ms) / 1000, 1),
                        "tts_estimated": round(tts_s, 1), "clip_durations_known": all(x is not None for x in seconds)},
    }


def main() -> int:
    runs = [r for r in load(ROOT / "results" / "run.jsonl") if "stt" in r]
    if not runs:
        print("No saved STT output. Run bench/run_benchmark.py first (this script makes no API calls).")
        return 2
    calls = {c.narrative["clip_id"]: c for c in load_calls(ROOT / "manifest.jsonl") if c.narrative}
    by_clip = {(r["clip_id"], r["condition"]): r for r in runs}
    out = []
    for run in runs:
        call = calls.get(run["clip_id"])
        if call is None:  # an answer clip: used inside its call's simulation
            continue
        out.append(simulate(call, run, by_clip))
        o = out[-1]
        print(f"  {o['clip_id']} [{o['condition']}] -> {o['status']}"
              f"{' (' + str(o['handoff_reason']) + ')' if o['handoff_reason'] else ''}"
              f" corrections={o['corrections']} wrong_confirmed={o['wrong_confirmed']}")
    dest = ROOT / "results" / "sim.jsonl"
    with dest.open("w", encoding="utf-8") as fh:
        for o in out:
            fh.write(json.dumps({**o, "generated_at": int(time.time())}, ensure_ascii=False) + "\n")
    print(f"Wrote {dest} ({len(out)} simulated calls)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

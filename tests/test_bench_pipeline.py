"""The benchmark scripts, end to end on invented transcripts: no API calls and no real audio."""

import json
import subprocess
from datetime import datetime

import numpy as np
import pytest

from app.gnani import stt
from app.nlp import timeparse
from bench import augment, check_corpus, make_manifest, report, run_benchmark, simulate_calls
from bench.corpus_lib import load_calls, manifest_problems, score_slot, within_precision
from tests.test_api import tone_wav

REF = datetime(2026, 11, 5, 12, 0)

# what Prisma "heard" for each clip of a 2-debit call
TRANSCRIPTS = {
    "c1_narrative": "SBI பேங்க்ல இருந்து கால் வந்துச்சு ஓடிபி கேட்டாங்க ₹40,000 போச்சு அப்புறம் ₹10,000 போச்சு",
    "c1_amount_1": "₹40,000",
    "c1_time_1": "nethu madhiyam moonu mani",
    "c1_utr_1": "430619827418",
    "c1_amount_2": "₹10,000",
    "c1_time_2": "nethu madhiyam naalu mani",
    "c1_utr_2": "43061982741",  # one digit lost: the validator must reject it, never guess
    "c1_bank": "எஸ்பிஐ",
    "c1_phone": "9876543218",
    "c1_yes": "ஆமா",
    "c1_no": "இல்ல",
    "c1_correction": "இல்ல கடைசி எட்டு",
    "c2_narrative": "என் போட்டோவை மார்ஃப் பண்ணி மிரட்டுறாங்க",
}


def call_row() -> dict:
    txns = [{"amount": 40000, "utr": "430619827418", "datetime": "04-11-2026 15:00"},
            {"amount": 10000, "utr": "430619827419", "datetime": "04-11-2026 16:00"}]
    turns = [{"clip_id": "c1_narrative", "slot": "narrative", "truth": {"amounts": [40000, 10000], "bank": "SBI"}}]
    for i, t in enumerate(txns, 1):
        turns += [{"clip_id": f"c1_amount_{i}", "slot": "amount", "truth": t["amount"], "txn": i - 1},
                  {"clip_id": f"c1_time_{i}", "slot": "datetime", "truth": t["datetime"], "txn": i - 1},
                  {"clip_id": f"c1_utr_{i}", "slot": "utr", "truth": t["utr"], "txn": i - 1}]
    turns += [{"clip_id": "c1_bank", "slot": "victim_bank", "truth": "SBI"},
              {"clip_id": "c1_phone", "slot": "suspect_phone", "truth": "9876543218"},
              {"clip_id": "c1_yes", "slot": "yes", "truth": "YES"}, {"clip_id": "c1_no", "slot": "no", "truth": "NO"},
              {"clip_id": "c1_correction", "slot": "correction", "truth": {"intent": "CORRECTION", "digits": "8"}}]
    return {"call_id": "c1", "script_id": "S1_OTP_BANK", "speaker": "spk1", "improvised": True,
            "reference_time": "2026-11-05T12:00", "turns": turns,
            "call_truth": {"txns": txns, "victim_bank": "SBI", "suspect_phone": "9876543218", "district": "Madurai"}}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    rows = [call_row(),
            {"call_id": "c2", "script_id": "S8_SEXTORTION_HANDOFF", "speaker": "spk1",
             "reference_time": "2026-11-05T12:00",
             "turns": [{"clip_id": "c2_narrative", "slot": "narrative", "truth": {}}],
             "call_truth": {"handoff": "HANDOFF_NONFIN"}}]
    (tmp_path / "manifest.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                                             encoding="utf-8")
    clean = tmp_path / "augmented" / "clean"
    clean.mkdir(parents=True)
    for i, cid in enumerate(TRANSCRIPTS):
        (clean / f"{cid}.wav").write_bytes(tone_wav(0.05 + i * 0.01))
    for mod in (run_benchmark, simulate_calls, report):
        monkeypatch.setattr(mod, "ROOT", tmp_path)

    async def fake_transcribe(wav, *, profile, request_id=None, **_):
        cid = request_id.removeprefix("bench-").rsplit("-", 1)[0]
        return stt.SttResult(TRANSCRIPTS[cid], TRANSCRIPTS[cid], "prisma-v2.5", None, False, 900, False)

    monkeypatch.setattr(stt, "transcribe", fake_transcribe)
    return tmp_path


async def test_pipeline_from_clips_to_results(workspace):
    assert await run_benchmark.main(["clean"], yes=True) == 0
    assert simulate_calls.main() == 0
    assert report.main() == 0
    rows = {r["clip_id"]: r for r in map(json.loads, (workspace / "results" / "run.jsonl").open(encoding="utf-8"))}
    assert rows["c1_time_1"]["fields"]["datetime (answer)"]["exact"]
    assert rows["c1_narrative"]["fields"]["all amounts in story"]["exact"]
    assert rows["c1_correction"]["fields"]["correction (answer)"]["exact"]
    assert not rows["c1_utr_2"]["fields"]["utr (answer)"]["exact"]

    sims = {s["call_id"]: s for s in map(json.loads, (workspace / "results" / "sim.jsonl").open(encoding="utf-8"))}
    assert set(sims) == {"c1", "c2"}, "an answer clip must not be simulated as its own call"
    assert sims["c1"]["status"] == "ready_for_review" and sims["c1"]["n_txns"] == 2
    assert sims["c1"]["wrong_confirmed"] == []
    assert sims["c1"]["voice_turns"] > 1, "answer clips must feed the FSM"
    assert sims["c2"]["status"] == "needs_human" and sims["c2"]["handoff_reason"] == "non_financial"

    text = (workspace / "RESULTS.md").read_text(encoding="utf-8")
    assert "utr (answer)" in text and "datetime (answer)" in text and "By speaker" in text
    assert "SIMULATION" in text and "Wrong digits that reached the packet as confirmed: 0" in text


async def test_report_drops_tts_clips_once_human_clips_exist(workspace):
    await run_benchmark.main(["clean"], yes=True)
    path = workspace / "results" / "run.jsonl"
    rows = list(map(json.loads, path.open(encoding="utf-8")))
    fake = {**rows[0], "clip_id": "tts_x", "synthetic_tts": True, "fields": {"amount": {"exact": True}}}
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [*rows, fake]), encoding="utf-8")
    report.main()
    text = (workspace / "RESULTS.md").read_text(encoding="utf-8")
    assert "1 TTS clips excluded" in text and "0 **TTS-generated**" in text


async def test_bad_manifest_stops_before_any_api_call(workspace, monkeypatch):
    row = call_row()
    row["turns"][3]["truth"] = "12345"  # a UTR with the wrong length
    (workspace / "manifest.jsonl").write_text(json.dumps(row), encoding="utf-8")

    async def boom(*a, **k):
        raise AssertionError("no STT call expected")

    monkeypatch.setattr(stt, "transcribe", boom)
    assert await run_benchmark.main(["clean"], yes=True) == 2


def test_more_than_fifty_live_calls_needs_approval(workspace, monkeypatch):
    import asyncio

    monkeypatch.setattr(run_benchmark, "would_cost", lambda *_: 51)
    assert asyncio.run(run_benchmark.main(["clean"], yes=False)) == 1
    assert not (workspace / "results").exists()


def test_flat_rows_still_load(tmp_path):
    p = tmp_path / "m.jsonl"
    p.write_text('{"clip_id": "a", "synthetic_tts": true, "field_truth": {"amount": 5}}\n', encoding="utf-8")
    c = load_calls(p)[0]
    assert c.call_id == "a" and c.synthetic_tts and c.narrative["truth"] == {"amount": 5}


@pytest.mark.parametrize("got,truth,precision,ok", [
    ("04-11-2026 15:00", "04-11-2026 15:00", None, True),
    ("04-11-2026 15:04", "04-11-2026 15:00", "minute", True),
    ("04-11-2026 15:30", "04-11-2026 15:00", "minute", False),
    ("04-11-2026 18:00", "04-11-2026 16:00", "part_of_day", True),
    ("04-11-2026 09:00", "04-11-2026 21:00", "day", True),
    ("03-11-2026 21:00", "04-11-2026 21:00", "day", False),
    (None, "04-11-2026 21:00", "day", False),
])
def test_within_precision(got, truth, precision, ok):
    assert within_precision(got, truth, precision) is ok


def test_called_bank_and_intent_slots():
    assert score_slot("called_bank", "no", "இல்ல", None, REF)["exact"]
    assert score_slot("yes", "YES", "சரி", None, REF)["exact"]
    assert not score_slot("yes", "YES", "இல்ல", None, REF)["exact"]


# ---------------------------------------------------------------- manifest generator
def test_generated_manifest_is_valid(tmp_path, monkeypatch):
    monkeypatch.setattr(make_manifest, "ROOT", tmp_path)
    (tmp_path / "manifest.jsonl").write_text('{"clip_id": "tts_a", "speaker": "tts-X", "field_truth": {}}\n',
                                             encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["x", "--speakers", "spk1,spk2", "--improvised", "spk1:S2_UPI_COLLECT",
                                     "--all-slots"])
    assert make_manifest.main() == 0
    calls = load_calls(tmp_path / "manifest.jsonl")
    assert len(calls) == 17, "16 acted calls, and the TTS row is kept"
    assert manifest_problems(calls) == []
    s1 = next(c for c in calls if c.call_id == "s1_spk1")
    assert len(s1.truth["txns"]) == 2
    assert len(next(c for c in calls if c.call_id == "s3_spk1").truth["txns"]) == 3
    assert next(c for c in calls if c.call_id == "s2_spk1").improvised
    sext = next(c for c in calls if c.call_id == "s8_spk1")
    assert sext.truth["handoff"] == "HANDOFF_NONFIN" and len(sext.turns) == 1


@pytest.mark.parametrize("script,txn", [(k, t) for k, v in make_manifest.SCRIPTS.items() for t in v["txns"]],
                         ids=lambda x: x if isinstance(x, str) else "")
def test_script_time_phrases_mean_their_truth(script, txn):
    """If the phrase on the script does not parse to the truth, a correct STT would score as wrong."""
    r = timeparse.parse_time(txn["say"], REF)
    assert within_precision(r.formatted(), txn["datetime"], r.precision), (txn["say"], r.formatted(), r.precision)


# ---------------------------------------------------------------- audio conditions
def test_mix_snr_hits_the_target():
    rng = np.random.default_rng(1)
    speech = 0.2 * np.sin(np.linspace(0, 2000, 16000)).astype(np.float32)
    noise = rng.normal(0, 0.1, 40000).astype(np.float32)
    mixed = augment.mix_snr(speech, noise, 10.0, rng)
    snr = 20 * np.log10(augment.rms(speech) / augment.rms(mixed - speech))
    assert snr == pytest.approx(10.0, abs=0.5)


def test_telephone_band_removes_high_frequencies():
    t = np.arange(16000) / 16000
    speech_band = 0.3 * np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    high = 0.3 * np.sin(2 * np.pi * 6000 * t).astype(np.float32)
    assert augment.rms(augment.telephone(high)) < 0.1 * augment.rms(augment.telephone(speech_band))


def test_augment_seed_is_per_clip(tmp_path, monkeypatch):
    corpus, noise = tmp_path / "corpus", tmp_path / "noise"
    corpus.mkdir()
    noise.mkdir()
    (corpus / "a.wav").write_bytes(tone_wav(0.2))
    (noise / "n.wav").write_bytes(augment.wav_bytes(np.random.default_rng(0).normal(0, 0.1, 16000)))
    monkeypatch.setattr(augment, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["x", "--corpus", str(corpus), "--conditions", "snr5"])
    assert augment.main() == 0
    first = (tmp_path / "augmented" / "snr5" / "a.wav").read_bytes()
    (corpus / "0_new.wav").write_bytes(tone_wav(0.2))  # sorts first: must not shift a.wav's noise
    assert augment.main() == 0
    assert (tmp_path / "augmented" / "snr5" / "a.wav").read_bytes() == first


def test_phone_m4a_with_index_at_the_end_loads(tmp_path):
    """Phone recorders write the MP4 index last, which ffmpeg cannot read from a pipe."""
    wav, m4a = tmp_path / "a.wav", tmp_path / "a.m4a"
    wav.write_bytes(tone_wav(0.5))
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(wav), "-c:a", "aac", str(m4a)], check=True)
    assert len(augment.load_clip(m4a)) > 6000


# ---------------------------------------------------------------- corpus check
def test_check_corpus_reports_what_is_missing(tmp_path, monkeypatch, capsys):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "c1_narrative.wav").write_bytes(tone_wav(0.2))
    (corpus / "stray.wav").write_bytes(tone_wav(0.2))
    (tmp_path / "manifest.jsonl").write_text(json.dumps(call_row()), encoding="utf-8")
    monkeypatch.setattr(check_corpus, "ROOT", tmp_path)
    assert check_corpus.main(min_speakers=3) == 1
    out = capsys.readouterr().out
    assert "c1_phone" in out and "stray.wav: not in the manifest" in out
    assert "needs 3" in out and "noise" in out and "NOT READY" in out

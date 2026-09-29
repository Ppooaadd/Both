"""Accuracy benchmark for analysis + arrangement.

    python -m bench.run [--songs a,b] [--fresh] [--separator demucs]

For every song in ``bench.songs.SPECS`` it runs the real pipeline stages
(separation is cached per song), then reports:

* beat F-measure and downbeat F-measure (70 ms window)
* melody transcription onset F1 (50 ms, pitch +-50 cents), from the analysis
* arrangement, per difficulty: melody-note recall against the original melody
  (pitch class, onset within a tolerance) and the median onset error, with
  times taken from the score's own tick -> source-time map
* render drift: how far the rendered piano audio's notes are from the original
  melody timing (what a listener hears as "off the beat")
"""

from __future__ import annotations

import argparse
import json
import pickle
import time
from pathlib import Path
from typing import Any

import mir_eval
import numpy as np

from bench.songs import REAL_VOCAL_TRACKS, SPECS, Song, build, real_vocal_song
from pianoforge.analysis.ir import AnalysisIR, StemInfo
from pianoforge.analysis.merge import merge_analysis
from pianoforge.analysis.registry import AdapterRegistry
from pianoforge.analysis.service import run_rhythm, run_separation, run_tonal, run_transcription
from pianoforge.arrangement.engine import arrange
from pianoforge.arrangement.params import ArrangementParams
from pianoforge.arrangement.score_ir import TPQ, ScoreIR
from pianoforge.config import Settings
from pianoforge.db.enums import Difficulty

CACHE = Path(__file__).resolve().parent / ".cache"


def hz(p: float) -> float:
    return 440.0 * 2 ** ((p - 69) / 12)


def separated(
    song: Song, registry: AdapterRegistry, fresh: bool
) -> tuple[str, dict[str, Any], list[str]]:
    """Separation is the slow step and does not change while tuning later stages."""
    CACHE.mkdir(exist_ok=True)
    engine = registry.separator.available()[0].name
    path = CACHE / f"{song.spec.name}-{engine}.pkl"
    if path.exists() and not fresh:
        return pickle.loads(path.read_bytes())  # type: ignore[no-any-return]  # noqa: S301 - own cache
    out = run_separation(song.mix, registry)
    data = (out.engine, dict(out.result.stems), list(out.result.warnings))
    path.write_bytes(pickle.dumps(data))
    return data


def analyse(
    song: Song, registry: AdapterRegistry, fresh: bool
) -> tuple[AnalysisIR, dict[str, float]]:
    t0 = time.perf_counter()
    engine, stems, warnings = separated(song, registry, fresh)
    t_sep = time.perf_counter() - t0
    t1 = time.perf_counter()
    rhythm = run_rhythm(song.mix, stems, registry)
    tonal = run_tonal(song.mix, stems, rhythm, registry)
    tx = run_transcription(song.mix, stems, registry)
    ir = merge_analysis(
        pipeline_version="bench",
        duration=song.mix.duration,
        sample_rate=song.mix.sample_rate,
        separator_engine=engine,
        stems=[
            StemInfo(kind=k, engine=engine, rms_db=b.rms_db(), storage_key=k)
            for k, b in stems.items()
        ],
        rhythm=rhythm,
        tonal=tonal,
        transcription=tx,
        extra_warnings=warnings,
    )
    return ir, {"sep_s": t_sep, "analysis_s": time.perf_counter() - t1}


def beat_metrics(song: Song, ir: AnalysisIR) -> dict[str, float]:
    ref = mir_eval.beat.trim_beats(np.asarray(song.beats), min_beat_time=0.0)
    est = np.asarray(ir.beats)
    dref = np.asarray(song.downbeats)
    dest = np.asarray(ir.downbeats)
    return {
        "beat_f": mir_eval.beat.f_measure(ref, est),
        "downbeat_f": mir_eval.beat.f_measure(dref, dest),
        "meter_ok": float(ir.time_signature.numerator == song.spec.meter),
        "bpm_est": ir.tempo.bpm,
    }


def melody_metrics(song: Song, ir: AnalysisIR) -> dict[str, float]:
    ref_iv = np.array([[n.t0, n.t1] for n in song.melody])
    ref_p = np.array([hz(n.pitch) for n in song.melody])
    notes = ir.tracks["melody"].notes
    if not notes:
        return {"mel_f": 0.0, "mel_p": 0.0, "mel_r": 0.0}
    est_iv = np.array([[n.start, max(n.end, n.start + 0.01)] for n in notes])
    est_p = np.array([hz(n.pitch) for n in notes])
    p, r, f, _ = mir_eval.transcription.precision_recall_f1_overlap(
        ref_iv, ref_p, est_iv, est_p, onset_tolerance=0.05, offset_ratio=None
    )
    return {"mel_p": p, "mel_r": r, "mel_f": f}


def tick_to_source(score: ScoreIR, tick: float) -> float:
    """Recording time of a written tick (swing applied, then the source beat map)."""
    performed = getattr(score, "performed_tick", None)
    if performed is not None:
        tick = performed(tick)
    bt = np.asarray(score.beat_times, dtype=np.float64)
    b = tick / TPQ
    if b <= len(bt) - 1:
        return float(np.interp(b, np.arange(len(bt)), bt))
    return float(bt[-1] + (b - (len(bt) - 1)) * (bt[-1] - bt[-2]))


def rendered_time(score: ScoreIR, tick: float) -> float:
    fn = getattr(score, "tick_to_seconds", None)
    if fn is not None:
        return float(fn(tick))
    return tick * score.seconds_per_tick()


def arrangement_metrics(song: Song, ir: AnalysisIR, level: Difficulty) -> dict[str, float]:
    score = arrange(ir, ArrangementParams(difficulty=level), song.spec.name)
    grid_beats = {
        Difficulty.beginner: 1.0,
        Difficulty.intermediate: 0.5,
        Difficulty.advanced: 0.25,
    }[level]
    mel = [n for n in score.notes if n.hand == "rh" and n.role == "melody"]
    est_t = np.array([tick_to_source(score, n.start) for n in mel])
    est_pc = np.array([(n.pitch - score.transpose) % 12 for n in mel])
    # Beat period around each reference note, for beat-relative tolerances.
    used = np.zeros(len(mel), dtype=bool)
    hits, on_grid, hits_grid, errs = 0, 0, 0, []
    for ref in song.melody:
        period = song.pos_to_time(ref.pos + 1) - song.pos_to_time(ref.pos)
        tol = max(0.06, 0.13 * period)
        is_on_grid = abs(ref.pos / grid_beats - round(ref.pos / grid_beats)) < 1e-6
        on_grid += is_on_grid
        if not len(mel):
            continue
        cand = np.flatnonzero(
            (~used)
            & (est_pc == ref.pitch % 12)
            & (np.abs(est_t - ref.t0) <= max(tol, 0.5 * grid_beats * period))
        )
        if cand.size:
            j = cand[np.argmin(np.abs(est_t[cand] - ref.t0))]
            err = abs(est_t[j] - ref.t0)
            if err <= tol:
                hits_grid += is_on_grid
            hits += 1
            used[j] = True
            errs.append(err)
    # Render drift: rendered time vs original time for matched notes, after
    # aligning the first melody note (a listener syncs to the start).
    drift = 0.0
    if len(mel) >= 2:
        r0 = rendered_time(score, mel[0].start)
        s0 = tick_to_source(score, mel[0].start)
        d = [
            abs((rendered_time(score, n.start) - r0) - (tick_to_source(score, n.start) - s0))
            for n in mel
        ]
        drift = float(np.percentile(d, 90))
    n_ref = len(song.melody)
    return {
        "recall": hits / n_ref,
        "recall_grid": hits_grid / max(on_grid, 1),
        "onset_err_ms": 1000 * float(np.median(errs)) if errs else float("nan"),
        "render_drift90_ms": 1000 * drift,
        "notes": len(mel),
        "precision": float(used.sum()) / max(len(mel), 1),
        "ref_notes": n_ref,
    }


def chord_metrics(song: Song, ir: AnalysisIR) -> dict[str, float]:
    # Root + maj/min agreement sampled every 100 ms over chorded time.
    ok = total = 0
    for t0, t1, root, q in song.chords:
        for t in np.arange(t0 + 0.05, t1 - 0.05, 0.1):
            total += 1
            est = next((c for c in ir.chords if c.start <= t < c.end), None)
            if est and est.root == root and (("min" in est.quality) == (q == "min")):
                ok += 1
    return {"chord_acc": ok / max(total, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", default="")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--real", action="store_true", help="add vocadito real-vocal songs")
    ap.add_argument("--beats", default="", help="beat tracker chain override, e.g. librosa,fixed")
    args = ap.parse_args()
    settings = Settings()
    if args.beats:
        settings = settings.model_copy(update={"beat_tracker_chain": args.beats.split(",")})
    registry = AdapterRegistry(settings)
    names = set(filter(None, args.songs.split(",")))
    rows = []
    songs: list[tuple[str, Any]] = [(spec.name, lambda spec=spec: build(spec)) for spec in SPECS]
    if args.real:
        songs += [(f"vocadito_{t}", lambda t=t: real_vocal_song(t)) for t in REAL_VOCAL_TRACKS]
    for name, make in songs:
        if names and name not in names:
            continue
        song = make()
        spec = song.spec
        ir, timing = analyse(song, registry, args.fresh)
        row: dict[str, Any] = {"song": spec.name, **timing}
        if spec.lead != "real":  # the singer is not on the band's beat grid
            row.update(beat_metrics(song, ir))
        row.update(melody_metrics(song, ir))
        row["mel_source"] = ir.tracks["melody"].source
        if spec.lead != "real":
            row.update(chord_metrics(song, ir))
        for level in Difficulty:
            if spec.lead == "real" and level != Difficulty.advanced:
                continue
            for k, v in arrangement_metrics(song, ir, level).items():
                row[f"{level.value[:3]}_{k}"] = v
        row["engines"] = ir.engines
        rows.append(row)
        print(
            json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items()}),
            flush=True,
        )

    keys = ["beat_f", "downbeat_f", "meter_ok", "mel_f", "chord_acc",
            "beg_recall_grid", "int_recall_grid", "adv_recall", "adv_recall_grid",
            "adv_precision", "adv_onset_err_ms", "adv_render_drift90_ms"]  # fmt: skip
    print("\n" + "song".ljust(16) + "".join(k[:14].rjust(15) for k in keys))
    for r in rows:
        print(r["song"].ljust(16) + "".join(f"{r.get(k, float('nan')):15.3f}" for k in keys))
    means = {k: float(np.nanmean([r.get(k, np.nan) for r in rows])) for k in keys}
    print("MEAN".ljust(16) + "".join(f"{means[k]:15.3f}" for k in keys))
    if args.out:
        Path(args.out).write_text(json.dumps({"rows": rows, "mean": means}, indent=1, default=str))


if __name__ == "__main__":
    main()

"""Beat This! (ISMIR 2024) transformer beat + downbeat tracker.

The network gives frame-wise beat and downbeat probabilities at 50 fps. On top
of its minimal peak picking we add what an arrangement needs:

* gap repair: beats missing in quiet or sparse passages are re-inserted and
  near-duplicate beats removed, so every bar has its full count of beats;
* downbeat evidence per beat: the network's downbeat curve blended with
  signal cues (bass/kick attacks, harmonic change);
* meter and bar phase together: Viterbi over position-in-bar for 3 and 4
  beats per bar, keeping the better-scoring meter. The path tolerates the odd
  irregular bar instead of shifting every following bar line.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar

import librosa
import numpy as np
import numpy.typing as npt

from pianoforge.analysis.adapters._rhythm import (
    HOP,
    beat_accents,
    regularity,
    tempo_curve,
)
from pianoforge.analysis.adapters._rhythm import SR as RHYTHM_SR
from pianoforge.analysis.interfaces import BeatResult, BeatTracker, ProgressFn, _noop
from pianoforge.analysis.ir import TimeSignature
from pianoforge.audio.buffer import AudioBuffer

FPS = 50
SR = 22_050
DEFAULT_CHECKPOINT = Path("/opt/models/beat_this/final0.ckpt")
# Log-probability of a bar that is shorter or longer than the meter.
IRREGULAR_BAR_LOGP = float(np.log(0.02))
# Mean per-beat log-likelihood by which 3/4 must beat 4/4.
METER_MARGIN = 0.02


@lru_cache(maxsize=1)
def _model(checkpoint: str) -> Any:
    import torch
    from beat_this.inference import Audio2Frames

    torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
    return Audio2Frames(checkpoint_path=checkpoint, device="cpu")


def _checkpoint() -> str:
    return str(DEFAULT_CHECKPOINT) if DEFAULT_CHECKPOINT.exists() else "final0"


def _sigmoid(x: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def pick_peaks(prob: npt.NDArray[np.float64], threshold: float = 0.5) -> npt.NDArray[np.int64]:
    """Local maxima within +-70 ms above ``threshold`` (the model's own rule)."""
    n = prob.size
    if n == 0:
        return np.zeros(0, dtype=np.int64)
    pad = np.pad(prob, 3, constant_values=-1.0)
    win = np.lib.stride_tricks.sliding_window_view(pad, 7)
    is_max = (prob >= win.max(axis=1)) & (prob > threshold)
    frames = np.flatnonzero(is_max)
    if frames.size > 1:  # plateaus -> keep the first frame of each run
        frames = frames[np.concatenate([[True], np.diff(frames) > 1])]
    return frames.astype(np.int64)


def refine_peaks(
    frames: npt.NDArray[np.int64], curve: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    """Sub-frame peak positions by parabolic interpolation (frames are 20 ms)."""
    f = frames.astype(np.float64)
    ok = (frames > 0) & (frames < curve.size - 1)
    i = frames[ok]
    a, b, c = curve[i - 1], curve[i], curve[i + 1]
    denom = a - 2 * b + c
    with np.errstate(divide="ignore", invalid="ignore"):
        off = np.where(np.abs(denom) > 1e-9, 0.5 * (a - c) / denom, 0.0)
    f[ok] = i + np.clip(off, -0.5, 0.5)
    return f


def repair_beats(
    beats: npt.NDArray[np.float64], prob: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    """Insert beats into gaps and drop near-duplicates, judged against the local period."""
    if beats.size < 4:
        return beats
    out = [float(beats[0])]
    for t in beats[1:]:
        local = _local_period(np.asarray([*out[-8:], float(t)]))
        gap = float(t) - out[-1]
        if gap < 0.55 * local:
            # Keep whichever of the two the network is more sure about.
            if prob[_frame(t, prob)] > prob[_frame(out[-1], prob)]:
                out[-1] = float(t)
            continue
        k = round(gap / local)
        if k >= 2 and abs(gap / k - local) < 0.25 * local:
            base = out[-1]
            out.extend([base + gap * j / k for j in range(1, k)])
        out.append(float(t))
    return np.asarray(out, dtype=np.float64)


def _local_period(times: npt.NDArray[np.float64]) -> float:
    d = np.diff(times)
    return float(np.median(d)) if d.size else 0.5


def _frame(t: float, prob: npt.NDArray[np.float64]) -> int:
    return int(min(max(round(t * FPS), 0), prob.size - 1))


def choose_meter(evidence: npt.NDArray[np.float64]) -> tuple[int, npt.NDArray[np.int64]]:
    """3 or 4 beats per bar: whichever bar-position path explains the evidence better.

    Scores are mean log-likelihoods per beat; 4/4 wins near-ties since it is by
    far the more common meter.
    """
    path3, score3 = bar_positions(evidence, 3)
    path4, score4 = bar_positions(evidence, 4)
    return (3, path3) if score3 > score4 + METER_MARGIN else (4, path4)


def bar_positions(
    db_prob: npt.NDArray[np.float64], meter: int
) -> tuple[npt.NDArray[np.int64], float]:
    """Viterbi over position-in-bar (0 = downbeat) for each beat.

    Regular motion p -> p+1 (mod meter) is free; jumping to 0 early (a short
    bar) or staying past the end (a long bar) costs IRREGULAR_BAR_LOGP.
    """
    n = db_prob.size
    eps = 1e-4
    emit_db = np.log(np.clip(db_prob, eps, 1 - eps))
    emit_other = np.log(np.clip(1 - db_prob, eps, 1 - eps))
    score = np.where(np.arange(meter) == 0, emit_db[0], emit_other[0]).astype(np.float64)
    back = np.zeros((n, meter), dtype=np.int64)
    for i in range(1, n):
        new = np.full(meter, -np.inf)
        arg = np.zeros(meter, dtype=np.int64)
        for p in range(meter):
            # regular successor
            q = (p + 1) % meter
            if score[p] > new[q]:
                new[q], arg[q] = score[p], p
            # irregular: early downbeat or an extra beat in the bar
            for q2 in (0, min(p + 1, meter - 1)):
                if q2 == q:
                    continue
                s = score[p] + IRREGULAR_BAR_LOGP
                if s > new[q2]:
                    new[q2], arg[q2] = s, p
        emit = np.where(np.arange(meter) == 0, emit_db[i], emit_other[i])
        score = new + emit
        back[i] = arg
    path = np.zeros(n, dtype=np.int64)
    path[-1] = int(np.argmax(score))
    best = float(score[path[-1]]) / max(n, 1)
    for i in range(n - 1, 0, -1):
        path[i - 1] = back[i, path[i]]
    return path, best


class BeatThisTracker(BeatTracker):
    name: ClassVar[str] = "beat_this"
    version: ClassVar[str] = "1.1"

    @classmethod
    def is_available(cls) -> bool:
        return importlib.util.find_spec("beat_this") is not None

    def track(
        self, mix: AudioBuffer, stems: Mapping[str, AudioBuffer], progress: ProgressFn = _noop
    ) -> BeatResult:
        model = _model(_checkpoint())
        progress(0.1)
        beat_logits, db_logits = model(mix.mono_at(SR), SR)
        progress(0.8)
        beat_prob = _sigmoid(beat_logits.cpu().numpy().astype(np.float64))
        db_prob = _sigmoid(db_logits.cpu().numpy().astype(np.float64))

        beats = refine_peaks(pick_peaks(beat_prob), beat_logits.cpu().numpy()) / FPS
        if beats.size < 4:
            raise ValueError("too few beats detected")
        beats = repair_beats(beats, beat_prob)

        # Downbeat evidence per beat: the network's downbeat curve near the beat,
        # blended with signal cues (bass/kick attacks, harmonic change). The
        # network is strong on pop/rock bars; the cues settle 3 vs 4 where its
        # downbeat curve is ambiguous.
        per_beat = np.array(
            [db_prob[max(0, _frame(t, db_prob) - 2) : _frame(t, db_prob) + 3].max() for t in beats]
        )
        y = mix.mono_at(RHYTHM_SR)
        frames = librosa.time_to_frames(beats, sr=RHYTHM_SR, hop_length=HOP).astype(np.int64)
        cues = beat_accents(y, frames)
        evidence = 0.6 * per_beat + 0.4 * cues
        meter, pos = choose_meter(np.clip(evidence, 0.0, 1.0))
        downbeats = beats[pos == 0]
        progress(1.0)

        bpm = 60.0 / float(np.median(np.diff(beats)))
        conf = float(np.mean(beat_prob[[_frame(t, beat_prob) for t in beats]]))
        return BeatResult(
            bpm=round(bpm, 2),
            beats=beats.astype(np.float32),
            downbeats=downbeats.astype(np.float32),
            time_signature=TimeSignature(numerator=meter, denominator=4),
            confidence=round(min(conf, 0.5 + 0.5 * regularity(beats)), 3),
            tempo_curve=tempo_curve(beats),
        )

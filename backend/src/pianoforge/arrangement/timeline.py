"""Mapping from the analysed beat grid (audio beats) to score ticks.

Score beat 0 is the first bar line. Analysis events carry fractional beat
indices (``start_beat``) relative to the first detected beat; the first
downbeat defines the bar phase. Material before it becomes a pickup bar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from pianoforge.analysis.ir import AnalysisIR
from pianoforge.arrangement.score_ir import TPQ, swing_map

STRAIGHT = 0.5

__all__ = ["STRAIGHT", "Timeline", "build_timeline", "detect_swing", "swing_map", "unswing"]


def unswing(frac: float, swing: float) -> float:
    """Played position within a beat -> written position (inverse of swing_map)."""
    if frac < swing:
        return frac / (2 * swing)
    return 0.5 + (frac - swing) / (2 * (1 - swing))


def detect_swing(beat_positions: list[float]) -> float:
    """Swing ratio of off-beat eighths (0.5 = straight, 2/3 = triplet swing).

    Onsets are folded into one beat. Swing needs a clear cluster around 2/3
    that outweighs straight eighths (1/2) and 16ths (3/4).
    """
    f = np.mod(np.asarray(beat_positions, dtype=np.float64), 1.0)
    swung = f[(f > 0.58) & (f < 0.73)]
    straight = np.sum(np.abs(f - 0.5) < 0.05) + np.sum(np.abs(f - 0.75) < 0.035)
    if swung.size < 8 or swung.size < 1.5 * straight:
        return STRAIGHT
    return float(np.clip(np.median(swung), 0.55, 0.72))


@dataclass(frozen=True)
class Timeline:
    beats_per_bar: int
    offset_beats: float  # add to an analysis beat index to get a score beat (whole beats)
    audio_beats: tuple[float, ...]  # analysis beat times (s)
    swing: float = STRAIGHT  # played position of the off-beat eighth

    @property
    def bar_ticks(self) -> int:
        return self.beats_per_bar * TPQ

    def to_ticks(self, analysis_beat: float) -> float:
        """Written score position; swung off-beats are straightened."""
        b = analysis_beat + self.offset_beats
        if self.swing != STRAIGHT:
            whole = math.floor(b)
            b = whole + unswing(b - whole, self.swing)
        return b * TPQ

    def beat_times(self, n_score_beats: int) -> list[float]:
        """Audio time of each score beat, extrapolating beyond the analysed beats."""
        b = np.asarray(self.audio_beats, dtype=np.float64)
        if b.size < 2:
            return [0.0] * n_score_beats
        idx = np.arange(n_score_beats, dtype=np.float64) - self.offset_beats
        first, last = b[1] - b[0], b[-1] - b[-2]
        out = np.interp(idx, np.arange(b.size), b)
        out = np.where(idx < 0, b[0] + idx * first, out)
        out = np.where(idx > b.size - 1, b[-1] + (idx - (b.size - 1)) * last, out)
        return [round(float(t), 4) for t in out]


def build_timeline(ir: AnalysisIR) -> Timeline:
    beats = np.asarray(ir.beats, dtype=np.float64)
    num = ir.time_signature.numerator
    d0 = int(np.argmin(np.abs(beats - ir.downbeats[0]))) if ir.downbeats and beats.size else 0
    earliest = min(
        [n.start_beat for t in ir.tracks.values() for n in t.notes if n.start_beat is not None]
        + [c.start_beat for c in ir.chords if c.start_beat is not None and c.root is not None]
        + [float(d0)]
    )
    # Whole pickup bars so that bar lines stay on downbeats.
    pickup_bars = max(0, math.ceil((d0 - earliest - 1e-6) / num))
    melody = ir.tracks.get("melody")
    swing = detect_swing(
        [n.start_beat for n in (melody.notes if melody else []) if n.start_beat is not None]
    )
    return Timeline(
        beats_per_bar=num,
        offset_beats=float(pickup_bars * num - d0),
        audio_beats=tuple(ir.beats),
        swing=swing,
    )


def quantize(ticks: float, grid: int) -> int:
    return round(ticks / grid) * grid


def choose_grid(onsets_ticks: list[float], grid: int, allow_triplets: bool) -> int:
    """Pick between the straight grid and an eighth-triplet grid by quantisation error.

    Straight is preferred unless triplets fit clearly better (swing, 12/8 feel).
    """
    if not allow_triplets or not onsets_ticks:
        return grid
    triplet = TPQ // 3
    x = np.asarray(onsets_ticks, dtype=np.float64)

    def err(g: int) -> float:
        return float(np.mean(np.abs(x - np.round(x / g) * g)) / g)

    return triplet if err(triplet) < 0.6 * err(grid) else grid

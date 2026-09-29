"""Dynamics that follow the recording: loudness per bar -> marks and velocities.

The analysis stores the mix loudness of every beat relative to the song's loud
passages. Bars are placed on the song's own loudness range (compressed pop
masters vary by only a few dB, orchestral recordings by 20+), mapped to
p / mp / mf / f, and a new mark is written only when a level holds for two
bars. Note velocities are scaled by the level so the rendered piano breathes
with the original.
"""

from __future__ import annotations

import numpy as np

from pianoforge.analysis.ir import AnalysisIR
from pianoforge.arrangement.events import Ev
from pianoforge.arrangement.score_ir import TPQ, DynamicMark
from pianoforge.arrangement.timeline import Timeline

LEVELS = ("pp", "p", "mp", "mf", "f", "ff")
VELOCITY_SCALE = {"pp": 0.55, "p": 0.7, "mp": 0.85, "mf": 1.0, "f": 1.14, "ff": 1.26}
# Below this spread (dB between quiet and loud bars) the song is one level.
FLAT_RANGE_DB = 3.0
HOLD_BARS = 2


def bar_levels(ir: AnalysisIR, tl: Timeline, measures: int, shift_beats: int) -> list[str]:
    """Dynamic level of every written bar (after intro cropping by ``shift_beats``)."""
    loud = np.asarray(ir.beat_loudness_db, dtype=np.float64)
    if loud.size == 0 or measures == 0:
        return ["mf"] * measures
    per_bar = []
    for m in range(measures):
        first = m * tl.beats_per_bar + shift_beats - tl.offset_beats
        idx = np.arange(int(first), int(first) + tl.beats_per_bar)
        idx = idx[(idx >= 0) & (idx < loud.size)]
        per_bar.append(float(np.mean(loud[idx])) if idx.size else np.nan)
    bars = np.asarray(per_bar)
    valid = bars[~np.isnan(bars)]
    if valid.size == 0:
        return ["mf"] * measures
    bars = np.where(np.isnan(bars), float(np.median(valid)), bars)
    # Smooth over neighbouring bars: dynamics are phrase-level, not beat-level.
    smooth = np.array([np.median(bars[max(0, i - 1) : i + 2]) for i in range(len(bars))])
    lo, hi = np.percentile(smooth, [10, 90])
    if hi - lo < FLAT_RANGE_DB:
        return ["mf"] * measures
    pos = np.clip((smooth - lo) / (hi - lo), 0.0, 1.0)
    raw = [("p" if x < 0.2 else "mp" if x < 0.45 else "mf" if x < 0.75 else "f") for x in pos]
    # Hysteresis: switch only when the new level holds for HOLD_BARS bars.
    out: list[str] = []
    cur = raw[0]
    for i, lv in enumerate(raw):
        if lv != cur and all(r == lv for r in raw[i : i + HOLD_BARS]):
            cur = lv
        out.append(cur)
    return out


def apply_dynamics(events: list[Ev], levels: list[str], bar_ticks: int) -> list[DynamicMark]:
    """Scale velocities bar by bar and return the marks to engrave."""
    for e in events:
        bar = min(max(e.start // bar_ticks, 0), len(levels) - 1) if levels else 0
        scale = VELOCITY_SCALE[levels[bar]] if levels else 1.0
        e.vel = int(np.clip(round(e.vel * scale), 1, 127))
    marks: list[DynamicMark] = []
    for i, lv in enumerate(levels):
        if not marks or marks[-1].mark != lv:
            marks.append(DynamicMark.model_validate({"start": i * bar_ticks, "mark": lv}))
    return marks


__all__ = ["LEVELS", "TPQ", "apply_dynamics", "bar_levels"]

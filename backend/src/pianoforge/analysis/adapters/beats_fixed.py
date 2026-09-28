"""Last-resort beat grid: constant 120 BPM in 4/4 from t=0."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

import numpy as np

from pianoforge.analysis.interfaces import BeatResult, BeatTracker, ProgressFn, _noop
from pianoforge.analysis.ir import TimeSignature
from pianoforge.audio.buffer import AudioBuffer

BPM = 120.0


class FixedBeatTracker(BeatTracker):
    name: ClassVar[str] = "fixed"
    version: ClassVar[str] = "1"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def track(
        self, mix: AudioBuffer, stems: Mapping[str, AudioBuffer], progress: ProgressFn = _noop
    ) -> BeatResult:
        period = 60.0 / BPM
        beats = np.arange(0.0, mix.duration, period, dtype=np.float64)
        progress(1.0)
        return BeatResult(
            bpm=BPM,
            beats=beats.astype(np.float32),
            downbeats=beats[::4].astype(np.float32),
            time_signature=TimeSignature(numerator=4, denominator=4),
            confidence=0.0,
            tempo_curve=[],
        )

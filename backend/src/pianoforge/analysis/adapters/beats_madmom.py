"""madmom RNN + DBN joint beat/downbeat tracker (optional ``beats`` extra)."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import ClassVar

import numpy as np

from pianoforge.analysis.adapters._rhythm import regularity, tempo_curve
from pianoforge.analysis.interfaces import BeatResult, BeatTracker, ProgressFn, _noop
from pianoforge.analysis.ir import TimeSignature
from pianoforge.audio.buffer import AudioBuffer

SR = 44_100


@lru_cache(maxsize=1)
def _importable() -> bool:
    # madmom 0.16 breaks on recent numpy/python at import time, so a spec check
    # is not enough; import it once and cache the answer.
    try:
        import madmom.features.downbeats  # noqa: F401
    except Exception:
        return False
    return True


class MadmomBeatTracker(BeatTracker):
    name: ClassVar[str] = "madmom"
    version: ClassVar[str] = "0.16"

    @classmethod
    def is_available(cls) -> bool:
        return _importable()

    def track(
        self, mix: AudioBuffer, stems: Mapping[str, AudioBuffer], progress: ProgressFn = _noop
    ) -> BeatResult:
        from madmom.audio.signal import Signal
        from madmom.features.downbeats import DBNDownBeatTrackingProcessor, RNNDownBeatProcessor

        sig = Signal(mix.mono_at(SR), sample_rate=SR, num_channels=1)
        act = RNNDownBeatProcessor()(sig)
        progress(0.7)
        res = DBNDownBeatTrackingProcessor(beats_per_bar=[3, 4], fps=100)(act)
        progress(1.0)
        if len(res) < 4:
            raise ValueError("too few beats detected")

        beats = np.asarray(res[:, 0], dtype=np.float64)
        positions = np.asarray(res[:, 1], dtype=np.int64)
        numerator = int(positions.max())
        downbeats = beats[positions == 1]
        bpm = 60.0 / float(np.median(np.diff(beats)))
        return BeatResult(
            bpm=round(bpm, 2),
            beats=beats.astype(np.float32),
            downbeats=downbeats.astype(np.float32),
            time_signature=TimeSignature(numerator=numerator, denominator=4),
            confidence=regularity(beats),
            tempo_curve=tempo_curve(beats),
        )

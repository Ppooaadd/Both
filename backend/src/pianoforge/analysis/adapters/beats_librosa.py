"""Dynamic-programming beat tracker (librosa) + heuristic meter/downbeats."""

from __future__ import annotations

import importlib.metadata
from collections.abc import Mapping
from typing import ClassVar

import librosa
import numpy as np

from pianoforge.analysis.adapters._rhythm import (
    HOP,
    SR,
    beat_accents,
    estimate_bpm,
    grid_bpm,
    infer_meter,
    regularity,
    snap_to_onsets,
    tempo_curve,
    trim_silent_beats,
)
from pianoforge.analysis.interfaces import BeatResult, BeatTracker, ProgressFn, _noop
from pianoforge.analysis.ir import TimeSignature
from pianoforge.audio.buffer import AudioBuffer


class LibrosaBeatTracker(BeatTracker):
    name: ClassVar[str] = "librosa"
    version: ClassVar[str] = importlib.metadata.version("librosa")

    @classmethod
    def is_available(cls) -> bool:
        return True

    def track(
        self, mix: AudioBuffer, stems: Mapping[str, AudioBuffer], progress: ProgressFn = _noop
    ) -> BeatResult:
        # The full mix is used on purpose: a drum stem alone is dominated by
        # broadband off-beat hi-hats, which pulls the beat phase by half a beat.
        y_mix = mix.mono_at(SR)
        onset_env = librosa.onset.onset_strength(y=y_mix, sr=SR, hop_length=HOP)
        progress(0.3)
        bpm = estimate_bpm(onset_env)
        # High tightness keeps the DP on the estimated period; snapping below
        # restores local timing.
        _, frames = librosa.beat.beat_track(
            onset_envelope=onset_env, sr=SR, hop_length=HOP, bpm=bpm, tightness=400, trim=False
        )
        progress(0.6)

        frames = snap_to_onsets(np.asarray(frames, dtype=np.int64), onset_env)
        frames = trim_silent_beats(frames, y_mix)
        if len(frames) < 4:
            raise ValueError("too few beats detected")
        beats = librosa.frames_to_time(frames, sr=SR, hop_length=HOP).astype(np.float64)

        accents = beat_accents(y_mix, frames)
        numerator, phase, _strength = infer_meter(accents)
        downbeats = beats[phase::numerator]
        progress(1.0)

        fitted = grid_bpm(beats)
        return BeatResult(
            bpm=round(fitted if 0.9 * bpm < fitted < 1.1 * bpm else bpm, 2),
            beats=beats.astype(np.float32),
            downbeats=downbeats.astype(np.float32),
            time_signature=TimeSignature(numerator=numerator, denominator=4),
            confidence=regularity(beats),
            tempo_curve=tempo_curve(beats),
        )

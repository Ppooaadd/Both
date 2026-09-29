"""Dynamic-programming beat tracker (librosa) + heuristic meter/downbeats."""

from __future__ import annotations

import importlib.metadata
from collections.abc import Mapping
from typing import ClassVar

import librosa
import numpy as np
import numpy.typing as npt
import scipy.ndimage

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

LOCAL_TEMPO_SMOOTH_S = 6.0
# |log2(local/global) - k| below this counts as an octave (metrical level) error.
OCTAVE_TOLERANCE = 0.1


def fold_octaves(local: npt.NDArray[np.float64], global_bpm: float) -> npt.NDArray[np.float64]:
    """Keep a local tempo curve in the same metrical level as the global tempo.

    Local estimates may lock onto eighth notes (2x) or half notes (0.5x). When
    the curve's median sits near a power-of-two multiple of the global tempo it
    is an octave error and the curve is scaled back; any other ratio (a real
    tempo change the global comb cannot represent) is trusted. Individual
    frames are then folded to within a factor sqrt(2) of the curve's centre.
    """
    centre = float(np.median(local))
    if centre <= 0 or global_bpm <= 0:
        return local
    octaves = float(np.log2(centre / global_bpm))
    k = round(octaves)
    if k != 0 and abs(octaves - k) < OCTAVE_TOLERANCE:
        local = local / 2.0**k
        centre /= 2.0**k
    lo, hi = centre / np.sqrt(2), centre * np.sqrt(2)
    out = local.astype(np.float64).copy()
    for _ in range(3):
        out = np.where(out > hi, out / 2, out)
        out = np.where(out < lo, out * 2, out)
    return out


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
        # Time-varying tempo (6 s median-smoothed local estimates under a broad
        # prior) lets the DP follow drift and tempo changes; snapping below
        # restores beat-level timing. Bench (fallback only): beat F 0.87 -> 0.93.
        local = librosa.feature.tempo(
            onset_envelope=onset_env,
            sr=SR,
            hop_length=HOP,
            aggregate=None,
            start_bpm=120.0,
            std_bpm=1.0,
            ac_size=8.0,
        )
        width = max(3, int(LOCAL_TEMPO_SMOOTH_S * SR / HOP))
        local = fold_octaves(scipy.ndimage.median_filter(local, size=width), bpm)
        _, frames = librosa.beat.beat_track(
            onset_envelope=onset_env, sr=SR, hop_length=HOP, bpm=local, tightness=100, trim=False
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

"""Shared tonal features: chroma extraction, beat segmentation, chord templates."""

from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np
import numpy.typing as npt

from pianoforge.analysis.interfaces import TonalInput

SR = 22_050
HOP = 512

F64 = npt.NDArray[np.float64]

# Intervals (semitones above root) per chord quality.
QUALITY_INTERVALS: dict[str, tuple[int, ...]] = {
    "maj": (0, 4, 7),
    "min": (0, 3, 7),
    "dim": (0, 3, 6),
    "aug": (0, 4, 8),
    "sus4": (0, 5, 7),
    "7": (0, 4, 7, 10),
    "maj7": (0, 4, 7, 11),
    "min7": (0, 3, 7, 10),
}
# Qualities a decoded triad may be refined into.
REFINEMENTS: dict[str, tuple[str, ...]] = {
    "maj": ("7", "maj7", "sus4", "aug"),
    "min": ("min7", "dim"),
}
REFINE_MARGIN = 0.04


def template(root: int, quality: str) -> F64:
    t = np.zeros(12, dtype=np.float64)
    for i, interval in enumerate(QUALITY_INTERVALS[quality]):
        t[(root + interval) % 12] = 1.2 if i == 0 else 1.0
    return t / np.linalg.norm(t)


@dataclass(frozen=True)
class BeatChroma:
    chroma: F64  # (12, n_segments), L2-normalised per column
    bass: F64 | None  # (12, n_segments), L2-normalised per column
    energy_db: F64  # (n_segments,) RMS in dB of the harmonic signal
    bounds: F64  # (n_segments + 1,) segment boundaries in seconds


def _cqt_chroma(y: npt.NDArray[np.float32]) -> F64:
    c = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=HOP, bins_per_octave=36, n_octaves=6)
    return np.asarray(c, dtype=np.float64)


def beat_chroma(data: TonalInput) -> BeatChroma:
    y = data.harmonic.mono_at(SR)
    duration = len(y) / SR
    chroma = _cqt_chroma(y)
    n_frames = chroma.shape[1]

    beats = np.asarray(data.beats, dtype=np.float64)
    beats = beats[(beats > 0.05) & (beats < duration - 0.05)]
    beat_frames = np.unique(
        np.clip(librosa.time_to_frames(beats, sr=SR, hop_length=HOP), 1, n_frames - 1)
    )
    frames = [0, *beat_frames.tolist(), n_frames]
    bounds = librosa.frames_to_time(np.asarray(frames), sr=SR, hop_length=HOP).astype(np.float64)
    bounds[-1] = duration

    sync = librosa.util.sync(chroma, beat_frames.tolist(), aggregate=np.median, pad=True)
    sync = sync / (np.linalg.norm(sync, axis=0, keepdims=True) + 1e-9)

    rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
    rms_sync = librosa.util.sync(rms[None, :], beat_frames.tolist(), aggregate=np.mean, pad=True)[0]
    energy_db = 20.0 * np.log10(np.maximum(rms_sync, 1e-6))

    bass_sync: F64 | None = None
    if data.bass is not None:
        yb = data.bass.mono_at(SR)
        if float(np.sqrt(np.mean(yb**2))) > 1e-4:
            cb = _cqt_chroma(yb)
            cb = cb[:, : chroma.shape[1]]
            bs = librosa.util.sync(cb, beat_frames.tolist(), aggregate=np.median, pad=True)
            bass_sync = bs / (np.linalg.norm(bs, axis=0, keepdims=True) + 1e-9)

    n = min(sync.shape[1], len(bounds) - 1, len(energy_db))
    return BeatChroma(
        chroma=sync[:, :n],
        bass=None if bass_sync is None else bass_sync[:, :n],
        energy_db=energy_db[:n],
        bounds=bounds[: n + 1],
    )

"""Loudness normalization (ITU-R BS.1770) with a peak ceiling."""

from __future__ import annotations

import numpy as np
import pyloudnorm as pyln

from pianoforge.audio.buffer import AudioBuffer

PEAK_CEILING = 10 ** (-1.0 / 20.0)  # -1 dBFS
MAX_GAIN_DB = 24.0  # never boost near-silence into noise


def integrated_lufs(buf: AudioBuffer) -> float:
    meter = pyln.Meter(buf.sample_rate)
    # pyloudnorm expects (frames, channels); needs at least one 400 ms block.
    if buf.duration < 0.5:
        return float("-inf")
    return float(meter.integrated_loudness(buf.samples.T.astype(np.float64)))


def normalize_loudness(buf: AudioBuffer, target_lufs: float) -> tuple[AudioBuffer, float]:
    """Return the normalized buffer and the applied gain in dB."""
    loudness = integrated_lufs(buf)
    if not np.isfinite(loudness):
        gain_db = 0.0
    else:
        gain_db = float(np.clip(target_lufs - loudness, -MAX_GAIN_DB, MAX_GAIN_DB))

    out = buf.samples * np.float32(10 ** (gain_db / 20.0))
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > PEAK_CEILING:
        scale = PEAK_CEILING / peak
        out = out * np.float32(scale)
        gain_db += 20.0 * float(np.log10(scale))
    return AudioBuffer(out.astype(np.float32), buf.sample_rate), gain_db

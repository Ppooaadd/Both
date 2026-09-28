"""Shared rhythm helpers: meter/downbeat inference, tempo curve, confidence."""

from __future__ import annotations

import librosa
import numpy as np
import numpy.typing as npt
import scipy.ndimage

SR = 22_050
HOP = 512
# A 3/4 hypothesis must beat 4/4 by this factor; most popular music is in 4.
TRIPLE_METER_PENALTY = 1.25


def _norm(x: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    x = x - x.min() if x.size else x
    peak = float(x.max()) if x.size else 0.0
    return x / peak if peak > 0 else x


def span_means(
    features: npt.NDArray[np.float64], frames: npt.NDArray[np.int64]
) -> npt.NDArray[np.float64]:
    """Mean feature vector per beat span ``[frames[i], frames[i+1])`` (last span to the end).

    Unlike ``librosa.util.sync`` there is no lead-in column, so column ``i``
    always belongs to beat ``i`` even when the first beat is frame 0.
    """
    n_cols = features.shape[1]
    bounds = [*np.clip(frames, 0, n_cols - 1).tolist(), n_cols]
    out = np.zeros((features.shape[0], len(frames)), dtype=np.float64)
    for i in range(len(frames)):
        a, b = bounds[i], max(bounds[i + 1], bounds[i] + 1)
        out[:, i] = features[:, a:b].mean(axis=1)
    return out


def _window_change(spans: npt.NDArray[np.float64], width: int) -> npt.NDArray[np.float64]:
    """Cosine distance between mean features of ``width`` beats before and after each beat.

    Averaging over several beats cancels beat-rate melodic motion and keeps
    bar-rate harmonic motion.
    """
    n = spans.shape[1]
    out = np.zeros(n, dtype=np.float64)
    for i in range(1, n):
        a = spans[:, max(0, i - width) : i].mean(axis=1)
        b = spans[:, i : i + width].mean(axis=1)
        denom = float(np.linalg.norm(a) * np.linalg.norm(b))
        out[i] = 1.0 - float(a @ b) / denom if denom > 0 else 0.0
    return out


def beat_accents(
    y_mix: npt.NDArray[np.float32], beat_frames: npt.NDArray[np.int64]
) -> npt.NDArray[np.float64]:
    """Per-beat downbeat evidence.

    Cues: low-band onsets (kick/bass attacks), harmonic change and bass-pitch
    change, the latter two measured over 2-beat windows.
    """
    n_frames = 1 + len(y_mix) // HOP
    frames = np.clip(beat_frames, 0, n_frames - 1)

    low = librosa.onset.onset_strength(
        y=y_mix, sr=SR, hop_length=HOP, n_fft=4096, fmax=160.0, n_mels=16
    )
    low_b = _norm(low[np.clip(frames, 0, len(low) - 1)].astype(np.float64))

    chroma = librosa.feature.chroma_cqt(y=y_mix, sr=SR, hop_length=HOP)
    harm_b = _norm(_window_change(span_means(chroma.astype(np.float64), frames), 2))

    bass_chroma = librosa.feature.chroma_cqt(
        y=y_mix, sr=SR, hop_length=HOP, fmin=librosa.note_to_hz("C1"), n_octaves=3
    )
    bass_b = _norm(_window_change(span_means(bass_chroma.astype(np.float64), frames), 2))

    return 0.3 * low_b + 0.35 * harm_b + 0.35 * bass_b


def infer_meter(accents: npt.NDArray[np.float64]) -> tuple[int, int, float]:
    """Return (numerator, downbeat_phase, strength) choosing between 3 and 4 beats per bar."""
    best: dict[int, tuple[int, float]] = {}
    for m in (3, 4):
        if len(accents) < 2 * m:
            best[m] = (0, 0.0)
            continue
        scores = []
        for phase in range(m):
            on = accents[phase::m]
            mask = np.ones(len(accents), dtype=bool)
            mask[phase::m] = False
            off = accents[mask]
            scores.append(float(on.mean() - (off.mean() if off.size else 0.0)))
        phase = int(np.argmax(scores))
        best[m] = (phase, scores[phase])
    if best[3][1] > best[4][1] * TRIPLE_METER_PENALTY and best[3][1] > 0:
        return 3, best[3][0], best[3][1]
    return 4, best[4][0], best[4][1]


def tempo_curve(beats: npt.NDArray[np.float64]) -> list[tuple[float, float]]:
    if len(beats) < 3:
        return []
    ibi = np.diff(beats)
    bpm = 60.0 / np.maximum(ibi, 1e-3)
    bpm = scipy.ndimage.median_filter(bpm, size=min(9, len(bpm) | 1))
    # Sample once per beat, rounded; the UI draws this as a line.
    return [(round(float(t), 3), round(float(b), 2)) for t, b in zip(beats[1:], bpm, strict=True)]


def regularity(beats: npt.NDArray[np.float64]) -> float:
    """1.0 for a perfectly steady grid, towards 0 for erratic beats."""
    if len(beats) < 4:
        return 0.0
    ibi = np.diff(beats)
    cv = float(np.std(ibi) / max(float(np.mean(ibi)), 1e-6))
    coverage = min(1.0, len(beats) / 16.0)
    return float(np.clip(1.0 - 2.0 * cv, 0.0, 1.0) * coverage)


def fold_tempo(bpm: float, low: float = 60.0, high: float = 190.0) -> float:
    while bpm < low:
        bpm *= 2.0
    while bpm > high:
        bpm /= 2.0
    return bpm


def estimate_bpm(
    onset_env: npt.NDArray[np.float32],
    low: float = 55.0,
    high: float = 200.0,
    prior_center: float = 110.0,
    prior_octaves: float = 1.0,
) -> float:
    """Global tempo from a comb over the onset autocorrelation.

    Stage 1 scores each candidate period by the autocorrelation at 1-4x the
    period (a true period has peaks at all multiples, which suppresses 2/3 and
    3/2 errors) under a weak log-normal prior. Stage 2 refines the winner with
    up to 16 multiples; fractional lags are read by linear interpolation, so
    the result is not quantised to whole frames.
    """
    x = onset_env.astype(np.float64) - float(onset_env.mean())
    ac = librosa.autocorrelate(x)
    if ac.size < 4 or ac[0] <= 0:
        return prior_center
    ac = ac / ac[0]
    idx = np.arange(ac.size, dtype=np.float64)

    def comb(bpms: npt.NDArray[np.float64], multiples: int) -> npt.NDArray[np.float64]:
        lags = 60.0 * SR / (HOP * bpms)
        score = np.zeros_like(bpms)
        for k in range(1, multiples + 1):
            score += np.interp(lags * k, idx, ac, right=0.0) / np.sqrt(k)
        return score

    coarse = np.arange(low, high, 0.1)
    prior = np.exp(-0.5 * (np.log2(coarse / prior_center) / prior_octaves) ** 2)
    best = float(coarse[int(np.argmax(np.clip(comb(coarse, 4), 0.0, None) * prior))])

    max_mult = int(max(1, min(16, (ac.size - 1) / (60.0 * SR / (HOP * best)))))
    fine = np.arange(best * 0.985, best * 1.015, 0.005)
    return float(fine[int(np.argmax(comb(fine, max_mult)))])


def grid_bpm(beats: npt.NDArray[np.float64]) -> float:
    """Tempo from a least-squares line through beat times (robust to frame quantisation)."""
    if len(beats) < 3:
        return 0.0
    slope = float(np.polyfit(np.arange(len(beats), dtype=np.float64), beats, 1)[0])
    return 60.0 / slope if slope > 0 else 0.0


def snap_to_onsets(
    frames: npt.NDArray[np.int64], onset_env: npt.NDArray[np.float32], radius: int = 2
) -> npt.NDArray[np.int64]:
    out = frames.copy()
    for i, f in enumerate(frames):
        lo, hi = max(0, int(f) - radius), min(len(onset_env), int(f) + radius + 1)
        if hi > lo:
            out[i] = lo + int(np.argmax(onset_env[lo:hi]))
    return np.unique(out)


def trim_silent_beats(
    frames: npt.NDArray[np.int64], y: npt.NDArray[np.float32], floor_db: float = -40.0
) -> npt.NDArray[np.int64]:
    """Drop leading/trailing beats placed in silence (the DP tracker fills the whole signal)."""
    rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
    if rms.size == 0 or float(rms.max()) <= 0:
        return frames
    level = 20.0 * np.log10(np.maximum(rms, 1e-10) / float(rms.max()))
    # Level over the span following each beat (up to the next beat).
    spans = span_means(level[None, :].astype(np.float64), frames)[0]
    loud = np.flatnonzero(spans > floor_db)
    if loud.size == 0:
        return frames
    return frames[loud[0] : loud[-1] + 1]

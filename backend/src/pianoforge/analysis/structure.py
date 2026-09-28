"""Coarse song-structure segmentation (A/B/C labels) on beat-synchronous features."""

from __future__ import annotations

import librosa
import numpy as np
import numpy.typing as npt

from pianoforge.analysis.ir import Section

SR = 22_050
HOP = 512
MIN_BEATS = 16
SAME_LABEL_SIMILARITY = 0.92
SECONDS_PER_SECTION = 20.0
MIN_SECTION_S = 4.0


def _snap(t: float, grid: npt.NDArray[np.float64]) -> float:
    if grid.size == 0:
        return t
    return float(grid[int(np.argmin(np.abs(grid - t)))])


def segment_sections(
    y: npt.NDArray[np.float32],
    beats: npt.NDArray[np.float64],
    downbeats: npt.NDArray[np.float64],
    duration: float,
) -> list[Section]:
    # >50 ms keeps frame 0 out of librosa.util.sync, which would drop the lead-in column.
    beats = beats[(beats > 0.05) & (beats < duration)]
    if len(beats) < MIN_BEATS:
        return [Section(start=0.0, end=duration, label="A")]

    frames = librosa.time_to_frames(beats, sr=SR, hop_length=HOP)
    chroma = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=HOP)
    mfcc = librosa.feature.mfcc(y=y, sr=SR, hop_length=HOP, n_mfcc=13)
    n = min(chroma.shape[1], mfcc.shape[1])
    feats = np.vstack([chroma[:, :n], mfcc[1:, :n]])
    sync = librosa.util.sync(feats, np.clip(frames, 0, n - 1).tolist(), aggregate=np.median)
    sync = (sync - sync.mean(axis=1, keepdims=True)) / (sync.std(axis=1, keepdims=True) + 1e-9)

    k = int(np.clip(round(duration / SECONDS_PER_SECTION), 2, 10))
    k = min(k, sync.shape[1] // 4) or 1
    bound_idx = librosa.segment.agglomerative(sync, k)
    # sync column 0 is [0, beats[0]); column i>0 starts at beats[i-1].
    starts = [0.0 if i == 0 else float(beats[min(i - 1, len(beats) - 1)]) for i in bound_idx]
    starts = sorted({_snap(s, downbeats) if s > 0 else 0.0 for s in starts} | {0.0})
    starts = [s for s in starts if s < duration]
    # Absorb short fragments (lead-in, pickup bars) into the preceding section,
    # or into the following one when the fragment is first. Sections stay contiguous.
    merged: list[float] = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else duration
        if merged and e - s < MIN_SECTION_S:
            continue
        merged.append(s)
    if len(merged) > 1 and merged[1] - merged[0] < MIN_SECTION_S:
        merged.pop(1)
    if len(merged) > 1 and duration - merged[-1] < MIN_SECTION_S:
        merged.pop()
    starts = merged
    ends = [*starts[1:], duration]

    # Segment-mean features for label clustering.
    col_times = np.concatenate([[0.0], beats])[: sync.shape[1]]
    reps: list[npt.NDArray[np.float64]] = []
    rep_labels: list[str] = []
    sections: list[Section] = []
    for s, e in zip(starts, ends, strict=True):
        cols = (col_times >= s) & (col_times < e)
        vec = sync[:, cols].mean(axis=1) if np.any(cols) else np.zeros(sync.shape[0])
        vec = vec / (np.linalg.norm(vec) + 1e-9)
        label = None
        if reps:
            sims = [float(vec @ r) for r in reps]
            best = int(np.argmax(sims))
            if sims[best] >= SAME_LABEL_SIMILARITY:
                label = rep_labels[best]
        if label is None:
            label = chr(ord("A") + min(len(reps), 25))
            reps.append(vec)
            rep_labels.append(label)
        if sections and sections[-1].label == label:
            prev = sections.pop()
            sections.append(Section(start=prev.start, end=e, label=label))
        else:
            sections.append(Section(start=s, end=e, label=label))
    return sections or [Section(start=0.0, end=duration, label="A")]

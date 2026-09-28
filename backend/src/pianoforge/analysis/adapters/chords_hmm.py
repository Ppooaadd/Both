"""Chord recognition on beat-synchronous chroma.

``HmmChordRecognizer``: 24 major/minor triads + "no chord" decoded with
Viterbi (self-transition bias smooths spurious one-beat changes), key-aware
prior, bass-chroma root support, then per-segment refinement into
7/maj7/min7/dim/aug/sus4 and slash-chord bass detection.

``TemplateChordRecognizer``: same features, independent per-beat argmax.
"""

from __future__ import annotations

from typing import ClassVar

import librosa
import numpy as np

from pianoforge.analysis.adapters._tonal import (
    F64,
    QUALITY_INTERVALS,
    REFINE_MARGIN,
    REFINEMENTS,
    BeatChroma,
    beat_chroma,
    template,
)
from pianoforge.analysis.interfaces import ChordRecognizer, ProgressFn, TonalInput, _noop
from pianoforge.analysis.ir import ChordSegment, KeyInfo

STATES: list[tuple[int | None, str]] = [
    *[(r, "maj") for r in range(12)],
    *[(r, "min") for r in range(12)],
    (None, "N"),
]
N_STATE = len(STATES) - 1
TEMPLATES = np.stack([template(r, q) for r, q in STATES[:N_STATE] if r is not None])  # (24, 12)

SOFTMAX_BETA = 14.0
BASS_ROOT_WEIGHT = 0.25
KEY_PRIOR_WEIGHT = 0.06
SILENCE_DB = -50.0
P_STAY = 0.82
MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
MINOR_SCALE = (0, 2, 3, 5, 7, 8, 10, 11)  # natural + raised 7th (harmonic minor V)


def _diatonic_bonus(key: KeyInfo) -> F64:
    scale = MAJOR_SCALE if key.mode == "major" else MINOR_SCALE
    pcs = {(key.tonic + s) % 12 for s in scale}
    bonus = np.zeros(N_STATE, dtype=np.float64)
    for i, (root, quality) in enumerate(STATES[:N_STATE]):
        assert root is not None
        tones = {(root + iv) % 12 for iv in QUALITY_INTERVALS[quality]}
        if tones <= pcs:
            bonus[i] = 1.0
    return bonus * KEY_PRIOR_WEIGHT * key.confidence


def _emission_scores(bc: BeatChroma, key: KeyInfo) -> F64:
    """(n_states, n_segments) unnormalised scores."""
    sim = TEMPLATES @ bc.chroma  # cosine similarity; both sides unit-norm
    if bc.bass is not None:
        roots = np.array([r for r, _ in STATES[:N_STATE]])
        sim = sim + BASS_ROOT_WEIGHT * bc.bass[roots, :]
    sim = sim + _diatonic_bonus(key)[:, None]

    silence = np.clip((SILENCE_DB + 10.0 - bc.energy_db) / 10.0, 0.0, 1.0)
    flat = 1.0 - (bc.chroma.max(axis=0) - bc.chroma.mean(axis=0))  # flat chroma -> noise
    n_score = 0.35 + 0.6 * silence + 0.1 * flat
    return np.vstack([sim, n_score[None, :]])


def _softmax(scores: F64) -> F64:
    z = SOFTMAX_BETA * (scores - scores.max(axis=0, keepdims=True))
    e = np.exp(z)
    return np.asarray(e / e.sum(axis=0, keepdims=True), dtype=np.float64)


def _refine(root: int, quality: str, chroma: F64) -> str:
    best_q = quality
    best = float(template(root, quality) @ chroma)
    for q in REFINEMENTS.get(quality, ()):
        s = float(template(root, q) @ chroma)
        if s > best + REFINE_MARGIN:
            best_q, best = q, s
    return best_q


def _slash_bass(root: int, quality: str, bass: F64 | None) -> int | None:
    if bass is None:
        return None
    pc = int(np.argmax(bass))
    if float(bass[pc]) < 0.6 or pc == root:
        return None
    chord_tones = {(root + iv) % 12 for iv in QUALITY_INTERVALS[quality]}
    return pc if pc in chord_tones else None


def _segments(path: list[int], probs: F64, bc: BeatChroma) -> list[ChordSegment]:
    out: list[ChordSegment] = []
    i = 0
    n = len(path)
    while i < n:
        j = i
        while j + 1 < n and path[j + 1] == path[i]:
            j += 1
        state = path[i]
        root, quality = STATES[state]
        start, end = float(bc.bounds[i]), float(bc.bounds[j + 1])
        conf = float(np.mean(probs[state, i : j + 1]))
        if end > start:
            if root is None:
                out.append(ChordSegment(start=start, end=end, quality="N", confidence=conf))
            else:
                w = np.diff(bc.bounds[i : j + 2])
                mean_chroma = bc.chroma[:, i : j + 1] @ w
                mean_chroma /= np.linalg.norm(mean_chroma) + 1e-9
                refined = _refine(root, quality, mean_chroma)
                mean_bass = None
                if bc.bass is not None:
                    mean_bass = bc.bass[:, i : j + 1] @ w
                    mean_bass /= np.linalg.norm(mean_bass) + 1e-9
                out.append(
                    ChordSegment(
                        start=start,
                        end=end,
                        root=root,
                        quality=refined,
                        bass=_slash_bass(root, refined, mean_bass),
                        confidence=conf,
                    )
                )
        i = j + 1
    return out


class HmmChordRecognizer(ChordRecognizer):
    name: ClassVar[str] = "hmm"
    version: ClassVar[str] = "1"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def recognize(
        self, data: TonalInput, key: KeyInfo, progress: ProgressFn = _noop
    ) -> list[ChordSegment]:
        bc = beat_chroma(data)
        progress(0.6)
        if bc.chroma.shape[1] == 0:
            return []
        probs = _softmax(_emission_scores(bc, key))
        transition = librosa.sequence.transition_loop(len(STATES), P_STAY)
        path = librosa.sequence.viterbi(probs, transition).tolist()
        progress(1.0)
        return _segments(path, probs, bc)


class TemplateChordRecognizer(ChordRecognizer):
    name: ClassVar[str] = "template"
    version: ClassVar[str] = "1"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def recognize(
        self, data: TonalInput, key: KeyInfo, progress: ProgressFn = _noop
    ) -> list[ChordSegment]:
        bc = beat_chroma(data)
        if bc.chroma.shape[1] == 0:
            return []
        probs = _softmax(_emission_scores(bc, key))
        path = np.argmax(probs, axis=0).tolist()
        progress(1.0)
        return _segments(path, probs, bc)

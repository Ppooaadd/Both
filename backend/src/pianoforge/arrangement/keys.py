"""Transposition, key simplification and key signatures."""

from __future__ import annotations

from typing import Literal

from pianoforge.analysis.ir import ChordSegment, KeyInfo
from pianoforge.arrangement.score_ir import ScoreKey

Mode = Literal["major", "minor"]

# Keys with at most one accidental: the beginner "easy key" targets.
EASY_TONICS: dict[str, tuple[int, ...]] = {"major": (0, 7, 5), "minor": (9, 2, 4)}

# Major-key tonic pitch class -> fifths. F#/Gb is written as Gb (6 flats).
_MAJOR_FIFTHS = {0: 0, 7: 1, 2: 2, 9: 3, 4: 4, 11: 5, 6: -6, 1: -5, 8: -4, 3: -3, 10: -2, 5: -1}


def signed_shift(semitones: int) -> int:
    """Map a pitch-class shift to the range -6..+5 (smallest move)."""
    s = semitones % 12
    return s - 12 if s > 5 else s


def easy_key_shift(tonic: int, mode: Mode) -> int:
    return min((signed_shift(t - tonic) for t in EASY_TONICS[mode]), key=lambda s: (abs(s), s))


def key_fifths(tonic: int, mode: Mode) -> int:
    major_tonic = tonic if mode == "major" else (tonic + 3) % 12
    return _MAJOR_FIFTHS[major_tonic]


def target_key(key: KeyInfo, transpose: int, simplify: bool) -> tuple[ScoreKey, int]:
    """Return the written key and the total semitone shift to apply."""
    shift = transpose
    if simplify:
        shift = easy_key_shift(key.tonic, key.mode) + transpose
    tonic = (key.tonic + shift) % 12
    return ScoreKey(tonic=tonic, mode=key.mode, fifths=key_fifths(tonic, key.mode)), shift


def transpose_chord(c: ChordSegment, shift: int) -> ChordSegment:
    if c.root is None:
        return c
    return c.model_copy(
        update={
            "root": (c.root + shift) % 12,
            "bass": None if c.bass is None else (c.bass + shift) % 12,
        }
    )

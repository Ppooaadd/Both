"""Mutable note event used while the engine builds a score."""

from __future__ import annotations

from dataclasses import dataclass

from pianoforge.arrangement.score_ir import Hand, NoteRole


@dataclass
class Ev:
    hand: Hand
    pitch: int
    start: int
    end: int
    vel: int
    role: NoteRole
    finger: int | None = None

    @property
    def dur(self) -> int:
        return self.end - self.start


def fold_into(pitch: int, lo: int, hi: int) -> int | None:
    """Move ``pitch`` by octaves into [lo, hi]; None when the window is under an octave."""
    while pitch < lo:
        pitch += 12
    while pitch > hi:
        pitch -= 12
    return pitch if lo <= pitch <= hi else None

"""Chord timeline on the score grid (harmonic rhythm per difficulty)."""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from pianoforge.analysis.adapters._tonal import QUALITY_INTERVALS
from pianoforge.analysis.ir import ChordSegment
from pianoforge.arrangement.score_ir import TPQ
from pianoforge.arrangement.timeline import Timeline

# Beginner: extended/altered chords reduced to the nearest triad.
_BEGINNER_QUALITY = {"7": "maj", "maj7": "maj", "min7": "min", "sus4": "maj", "aug": "maj"}


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    root: int
    quality: str
    bass: int | None

    @property
    def pcs(self) -> list[int]:
        """Chord tones, root first (root, third, fifth[, seventh])."""
        return [(self.root + iv) % 12 for iv in QUALITY_INTERVALS[self.quality]]

    @property
    def bass_pc(self) -> int:
        return self.bass if self.bass is not None else self.root


def slot_ticks(harmonic_slot_beats: int, beats_per_bar: int) -> int:
    # Odd meters (3/4) change at most once per bar at the half-bar levels.
    if harmonic_slot_beats >= 2 and beats_per_bar % 2:
        return beats_per_bar * TPQ
    return harmonic_slot_beats * TPQ


def chord_spans(
    chords: list[ChordSegment],
    tl: Timeline,
    total_ticks: int,
    slot: int,
    simplify: bool,
) -> list[Span]:
    segs = [
        (tl.to_ticks(c.start_beat), tl.to_ticks(c.end_beat), c)
        for c in chords
        if c.root is not None and c.start_beat is not None and c.end_beat is not None
    ]
    slots: list[tuple[int, str, int | None] | None] = []
    prev: tuple[int, str, int | None] | None = None
    for s in range(0, total_ticks, slot):
        e = s + slot
        best, best_overlap = None, 0.0
        for cs, ce, c in segs:
            overlap = min(e, ce) - max(s, cs)
            if overlap > best_overlap:
                best, best_overlap = c, overlap
        if best is None or best_overlap < slot * 0.25:
            slots.append(prev)  # no clear chord: hold the previous one
            continue
        assert best.root is not None
        quality = _BEGINNER_QUALITY.get(best.quality, best.quality) if simplify else best.quality
        cur = (best.root, quality, None if simplify else best.bass)
        slots.append(cur)
        prev = cur

    spans: list[Span] = []
    for i, chosen in enumerate(slots):
        if chosen is None:
            continue
        s = i * slot
        if (
            spans
            and spans[-1].end == s
            and (spans[-1].root, spans[-1].quality, spans[-1].bass) == chosen
        ):
            last = spans[-1]
            spans[-1] = Span(last.start, s + slot, last.root, last.quality, last.bass)
        else:
            spans.append(Span(s, s + slot, *chosen))
    return spans


class ChordLookup:
    def __init__(self, spans: list[Span]) -> None:
        self.spans = spans
        self._starts = [s.start for s in spans]

    def at(self, tick: int) -> Span | None:
        i = bisect.bisect_right(self._starts, tick) - 1
        if i >= 0 and self.spans[i].start <= tick < self.spans[i].end:
            return self.spans[i]
        return None

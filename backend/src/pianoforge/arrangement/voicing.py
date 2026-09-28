"""Left-hand chord voicings with minimal voice movement.

Candidates are close-position inversions (optionally with the fifth omitted)
inside a register window. The chosen voicing minimises:

* voice-leading distance from the previous voicing,
* distance of its centre from the register centre,
* "mud": close intervals (<= major third) below C3 sound muddy on a piano.
"""

from __future__ import annotations

import itertools

MUD_FLOOR = 48  # C3
MUD_PENALTY = 4.0
CENTER_WEIGHT = 0.15


def place(pc: int, lo: int, hi: int, near: int | None = None) -> int | None:
    """Pitch with class ``pc`` inside [lo, hi], closest to ``near`` (lowest if None)."""
    options = [p for p in range(lo, hi + 1) if p % 12 == pc]
    if not options:
        return None
    if near is None:
        return options[0]
    return min(options, key=lambda p: (abs(p - near), p))


def _reduce(pcs: list[int], size: int) -> list[int]:
    """Drop tones by priority (fifth first, then root) keeping third and seventh."""
    if len(pcs) <= size:
        return list(pcs)
    order = list(pcs)
    drop_priority = [2, 0, 3, 1]  # indices: fifth, root, seventh, third
    for idx in drop_priority:
        if len(order) <= size:
            break
        if idx < len(pcs) and pcs[idx] in order:
            order.remove(pcs[idx])
    return order[:size]


def candidates(
    pcs: list[int], size: int, lo: int, hi: int, max_span: int, root_bottom: bool = False
) -> list[tuple[int, ...]]:
    tones = _reduce(pcs, size)
    out: set[tuple[int, ...]] = set()
    for perm in {tuple(tones[i:] + tones[:i]) for i in range(len(tones))}:
        if root_bottom and perm[0] != pcs[0]:
            continue
        for base in range(lo, hi + 1):
            if base % 12 != perm[0]:
                continue
            voicing = [base]
            for pc in perm[1:]:
                nxt = voicing[-1] + ((pc - voicing[-1]) % 12 or 12)
                voicing.append(nxt)
            if voicing[-1] <= hi and voicing[-1] - voicing[0] <= max_span:
                out.add(tuple(voicing))
    return sorted(out)


def _movement(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    if len(a) == len(b):
        return float(sum(abs(x - y) for x, y in zip(a, b, strict=True)))
    # Different sizes: compare every voice with its nearest counterpart.
    return float(sum(min(abs(x - y) for y in a) for x in b))


def _mud(v: tuple[int, ...]) -> float:
    return sum(MUD_PENALTY for x, y in itertools.pairwise(v) if x < MUD_FLOOR and y - x <= 4)


def choose(
    cands: list[tuple[int, ...]], prev: tuple[int, ...] | None, center: float
) -> tuple[int, ...] | None:
    if not cands:
        return None

    def cost(v: tuple[int, ...]) -> float:
        c = CENTER_WEIGHT * abs(sum(v) / len(v) - center) + _mud(v)
        if prev is not None:
            c += _movement(prev, v)
        return c

    return min(cands, key=cost)


class VoiceLeader:
    """Stateful voicing chooser for a sequence of chords."""

    def __init__(self, lo: int, hi: int, max_span: int) -> None:
        self.lo, self.hi, self.max_span = lo, hi, max_span
        self.prev: tuple[int, ...] | None = None

    @property
    def center(self) -> float:
        return (self.lo + self.hi) / 2

    def next(self, pcs: list[int], size: int, root_bottom: bool = False) -> tuple[int, ...]:
        for s in range(size, 0, -1):
            v = choose(
                candidates(pcs, s, self.lo, self.hi, self.max_span, root_bottom),
                self.prev,
                self.center,
            )
            if v is not None:
                self.prev = v
                return v
        return ()

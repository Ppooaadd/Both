"""Heuristic piano fingering.

The top line of the right hand (and the bottom line of the left hand) is
fingered with dynamic programming over fingers 1-5. Transition costs follow
the idea of Parncutt et al. (1997): each finger pair has a comfortable span;
stretching beyond it, reusing a finger on a different key, crossing, and
putting the thumb on a black key all cost more. Remaining chord tones are
fingered by position around the line note.

The left hand is solved by mirroring pitches, since LH fingering is the mirror
image of RH fingering.
"""

from __future__ import annotations

from pianoforge.arrangement.events import Ev

FINGERS = (1, 2, 3, 4, 5)
BLACK_KEYS = {1, 3, 6, 8, 10}

# Comfortable (min, max) semitone distance for ascending finger pairs (lower, higher).
COMFORT: dict[tuple[int, int], tuple[int, int]] = {
    (1, 2): (1, 5), (1, 3): (3, 7), (1, 4): (5, 9), (1, 5): (7, 10),
    (2, 3): (1, 2), (2, 4): (3, 4), (2, 5): (5, 6),
    (3, 4): (1, 2), (3, 5): (3, 4),
    (4, 5): (1, 2),
}  # fmt: skip
MAX_STRETCH: dict[tuple[int, int], int] = {
    (1, 2): 10, (1, 3): 12, (1, 4): 13, (1, 5): 15,
    (2, 3): 4, (2, 4): 6, (2, 5): 8,
    (3, 4): 3, (3, 5): 5,
    (4, 5): 4,
}  # fmt: skip


def transition_cost(f1: int, p1: int, f2: int, p2: int) -> float:
    d = p2 - p1
    if f1 == f2:
        return 0.0 if d == 0 else 6.0 + abs(d)
    if d == 0:
        return 1.0  # finger change on a repeated note: fine, slightly worse
    lo, hi = min(f1, f2), max(f1, f2)
    natural = (f2 > f1) == (d > 0)  # higher finger for a higher note
    cost = 0.0
    if natural:
        cmin, cmax = COMFORT[(lo, hi)]
        dist = abs(d)
        if dist > MAX_STRETCH[(lo, hi)]:
            cost += 10.0 + 2.0 * (dist - MAX_STRETCH[(lo, hi)])
        elif dist > cmax:
            cost += 1.0 * (dist - cmax)
        elif dist < cmin:
            cost += 0.8 * (cmin - dist)
    else:
        # Crossing: only thumb-under (ascending onto 1) or finger-over (descending from 1).
        if 1 in (f1, f2) and abs(d) <= 5 and hi <= 4:
            cost += 3.0 + 0.7 * abs(d)
        else:
            cost += 12.0 + abs(d)
    if f2 == 1 and p2 % 12 in BLACK_KEYS:
        cost += 1.5
    if f2 == 4:
        cost += 0.3  # weakest finger
    return cost


def chord_cost(f: int, n_others: int, span: int) -> float:
    """Cost of line finger ``f`` when ``n_others`` tones below it (RH orientation) span ``span``."""
    if n_others == 0:
        return 0.0
    cost = 8.0 * max(0, n_others - (f - 1))  # not enough fingers left for the chord
    if f > 1 and span > MAX_STRETCH[(1, f)]:
        cost += 3.0 * (span - MAX_STRETCH[(1, f)])
    return cost


def finger_line(pitches: list[int], chords: list[tuple[int, int]] | None = None) -> list[int]:
    """Viterbi over fingers for a line (right-hand orientation).

    ``chords[i] = (n_other_tones, span)`` describes the chord under line note i.
    """
    if not pitches:
        return []
    chords = chords or [(0, 0)] * len(pitches)
    INF = float("inf")
    cost = [{f: (0.3 if f == 4 else 0.0) + chord_cost(f, *chords[0]) for f in FINGERS}]
    back: list[dict[int, int]] = [{}]
    for i in range(1, len(pitches)):
        cur: dict[int, float] = {}
        ptr: dict[int, int] = {}
        for f2 in FINGERS:
            best, arg = INF, 1
            for f1 in FINGERS:
                c = (
                    cost[-1][f1]
                    + transition_cost(f1, pitches[i - 1], f2, pitches[i])
                    + chord_cost(f2, *chords[i])
                )
                if c < best:
                    best, arg = c, f1
            cur[f2], ptr[f2] = best, arg
        cost.append(cur)
        back.append(ptr)
    f = min(cost[-1], key=lambda k: cost[-1][k])
    path = [f]
    for i in range(len(pitches) - 1, 0, -1):
        f = back[i][f]
        path.append(f)
    return path[::-1]


def assign_fingering(events: list[Ev]) -> None:
    """Set ``finger`` on every note (in place)."""
    for hand in ("rh", "lh"):
        chords: dict[int, list[Ev]] = {}
        for e in events:
            if e.hand == hand:
                chords.setdefault(e.start, []).append(e)
        if not chords:
            continue
        starts = sorted(chords)
        # Line note: top of RH chords, bottom of LH chords.
        line = [
            max(chords[s], key=lambda e: e.pitch)
            if hand == "rh"
            else min(chords[s], key=lambda e: e.pitch)
            for s in starts
        ]
        # Mirror LH so that "higher finger for higher note" holds.
        pitches = [e.pitch if hand == "rh" else -e.pitch for e in line]
        shapes = [
            (len(chords[s]) - 1, max(e.pitch for e in chords[s]) - min(e.pitch for e in chords[s]))
            for s in starts
        ]
        fingers = finger_line(pitches, shapes)
        for s, note, f in zip(starts, line, fingers, strict=True):
            note.finger = f
            others = sorted((e for e in chords[s] if e is not note), key=lambda e: e.pitch)
            if hand == "rh":
                # Tones below the top line get lower fingers, from the bottom up.
                available = list(range(1, f))
                for e, fg in zip(others, available[: len(others)], strict=False):
                    e.finger = fg
            else:
                # Tones above the bass: the highest takes the thumb, then 2, 3, ...
                available = list(range(1, f))
                for e, fg in zip(reversed(others), available[: len(others)], strict=False):
                    e.finger = fg

"""Right-hand harmonisation: chord tones added under the melody.

* intermediate: one tone (a third or sixth below) on strong beats of notes >= 1 beat
* advanced:     up to two tones, also on long weak-beat notes, plus optional
                octave doubling of long strong-beat melody notes
"""

from __future__ import annotations

from pianoforge.arrangement.events import Ev
from pianoforge.arrangement.harmony import ChordLookup
from pianoforge.arrangement.profiles import Profile
from pianoforge.arrangement.score_ir import TPQ
from pianoforge.db.enums import Difficulty

RH_FLOOR = 53  # F3: below this the right hand collides with left-hand chords
# Preferred distance below the melody for the first added voice (thirds, sixths).
PREFERRED_FIRST = (3, 4, 8, 9)


def _strong(tick: int, beats_per_bar: int) -> bool:
    pos = tick % (beats_per_bar * TPQ)
    return pos == 0 or (beats_per_bar % 2 == 0 and pos == (beats_per_bar // 2) * TPQ)


def harmonize(
    melody: list[Ev], chords: ChordLookup, profile: Profile, beats_per_bar: int
) -> list[Ev]:
    if profile.rh_extra_voices <= 0:
        return []
    added: list[Ev] = []
    for m in melody:
        strong = _strong(m.start, beats_per_bar)
        long_note = m.dur >= 2 * TPQ
        if m.dur < TPQ:
            continue
        if not strong and not (profile.difficulty == Difficulty.advanced and long_note):
            continue
        span = chords.at(m.start)
        if span is None:
            continue
        floor = max(RH_FLOOR, m.pitch - profile.max_span)
        tones: list[int] = []

        if profile.octave_doubling and strong and long_note and m.pitch - 12 >= floor:
            tones.append(m.pitch - 12)

        pcs = set(span.pcs)
        pool = [
            p for p in range(m.pitch - 1, floor - 1, -1) if p % 12 in pcs and p % 12 != m.pitch % 12
        ]
        if not pool:
            pool = [p for p in range(m.pitch - 3, floor - 1, -1) if p % 12 in pcs]
        first = sorted(pool, key=lambda p: (m.pitch - p not in PREFERRED_FIRST, m.pitch - p))
        for p in first:
            if len(tones) >= profile.rh_extra_voices:
                break
            if all(abs(p - t) >= 3 for t in tones):
                tones.append(p)

        for p in tones[: profile.rh_extra_voices]:
            added.append(Ev("rh", p, m.start, m.end, max(1, m.vel - 18), "harmony"))
    return added

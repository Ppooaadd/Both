"""Right-hand melody: selection, quantisation, simplification and register fitting."""

from __future__ import annotations

import itertools

from pianoforge.analysis.ir import AnalysisIR, NoteEvent
from pianoforge.analysis.merge import reduce_monophonic
from pianoforge.arrangement.events import Ev, fold_into
from pianoforge.arrangement.params import MelodySource
from pianoforge.arrangement.profiles import Profile
from pianoforge.arrangement.score_ir import TPQ
from pianoforge.arrangement.timeline import Timeline, quantize


def select_melody(ir: AnalysisIR, source: MelodySource) -> tuple[list[NoteEvent], str]:
    """Return the melody line and a description of where it came from."""
    melody = ir.tracks.get("melody")
    harmony = ir.tracks.get("harmony")
    wants_other = source == "other" or (source == "vocals" and melody and melody.source != "vocals")
    if wants_other and harmony and harmony.notes:
        return reduce_monophonic(list(harmony.notes), prefer="high"), "harmony top voice"
    if melody and melody.notes:
        return list(melody.notes), f"{melody.source} ({melody.engine})"
    if harmony and harmony.notes:
        return reduce_monophonic(list(harmony.notes), prefer="high"), "harmony top voice"
    return [], "none"


# Typical salience of a clear note (velocity ~90, confidence ~0.6, 0.3 s):
# dividing by this puts salience on the same scale as the distance term.
SALIENCE_SCALE = 150.0
# A note half a grid step away must be about twice as salient to win the slot.
DISTANCE_WEIGHT = 2.0


def _salience(n: NoteEvent) -> float:
    # Loud, confident and long notes win quantisation collisions.
    return n.velocity * (0.5 + n.confidence) + 2.0 * (n.end - n.start)


def build_melody(
    notes: list[NoteEvent], tl: Timeline, shift: int, profile: Profile, grid: int
) -> list[Ev]:
    # 1. Quantise. When several notes land on one grid point, the note played
    #    closest to it wins (a note on the beat beats an off-beat neighbour
    #    that rounds onto the same beat); salience breaks near-ties.
    by_onset: dict[int, tuple[float, Ev]] = {}
    for n in notes:
        if n.start_beat is None or n.end_beat is None:
            continue
        raw = tl.to_ticks(n.start_beat)
        s = quantize(raw, grid)
        e = quantize(tl.to_ticks(n.end_beat), grid)
        if s < 0:
            continue
        e = max(e, s + grid)
        ev = Ev("rh", n.pitch + shift, s, e, n.velocity, "melody")
        score = _salience(n) / SALIENCE_SCALE - DISTANCE_WEIGHT * abs(raw - s) / grid
        if s not in by_onset or score > by_onset[s][0]:
            by_onset[s] = (score, ev)
    events = [ev for _, ev in sorted(by_onset.values(), key=lambda x: x[1].start)]

    # 2. Monophony: each note ends by the next onset.
    for a, b in itertools.pairwise(events):
        a.end = min(a.end, b.start)

    # 3. Drop notes shorter than the level allows unless they sit on a beat;
    #    the previous note absorbs the time so rhythm stays continuous.
    kept: list[Ev] = []
    for ev in events:
        if ev.dur < profile.min_melody_ticks and ev.start % TPQ != 0 and kept:
            kept[-1].end = ev.end
            continue
        kept.append(ev)

    # 4. Legato: close gaps shorter than a beat.
    for a, b in itertools.pairwise(kept):
        if 0 < b.start - a.end < TPQ:
            a.end = b.start

    fit_register(kept, profile)
    limit_leaps(kept, profile)
    return kept


def fit_register(events: list[Ev], profile: Profile) -> None:
    """Global octave shift that keeps most notes in range, then fold the outliers."""
    if not events:
        return
    lo, hi = profile.rh_range
    best = min(
        (-36, -24, -12, 0, 12, 24, 36),
        key=lambda k: (sum(not lo <= e.pitch + k <= hi for e in events), abs(k)),
    )
    for e in events:
        folded = fold_into(e.pitch + best, lo, hi)
        e.pitch = folded if folded is not None else e.pitch + best


def limit_leaps(events: list[Ev], profile: Profile) -> None:
    lo, hi = profile.rh_range
    for prev, cur in itertools.pairwise(events):
        leap = cur.pitch - prev.pitch
        if abs(leap) <= profile.max_melody_leap:
            continue
        alt = cur.pitch - 12 if leap > 0 else cur.pitch + 12
        if lo <= alt <= hi and abs(alt - prev.pitch) < abs(leap):
            cur.pitch = alt

"""Enforce physical constraints so every output is playable at its level.

Per hand, in order:
1. fold notes into the user's allowed range
2. turn the hand into a chord stream (same-onset notes share a duration,
   each chord ends by the next onset, duplicate pitches removed)
3. cap simultaneous notes (``max_poly``) and hand span (``max_span``)
   - right hand drops the lowest non-melody tones first
   - left hand keeps the bass and drops from the top
4. resolve hand collisions: a left-hand note at or above the lowest sounding
   right-hand note moves down an octave, or is dropped
"""

from __future__ import annotations

from collections import defaultdict

from pianoforge.arrangement.events import Ev, fold_into
from pianoforge.arrangement.profiles import Profile


def chord_stream(events: list[Ev]) -> list[list[Ev]]:
    groups: dict[int, dict[int, Ev]] = defaultdict(dict)
    for e in events:
        cur = groups[e.start].get(e.pitch)
        # Keep the more important duplicate (melody > bass > others).
        rank = {"melody": 3, "bass": 2, "harmony": 1, "accomp": 0}
        if cur is None or rank[e.role] > rank[cur.role]:
            groups[e.start][e.pitch] = e
    starts = sorted(groups)
    out: list[list[Ev]] = []
    for i, s in enumerate(starts):
        chord = sorted(groups[s].values(), key=lambda e: e.pitch)
        end = max(e.end for e in chord)
        if i + 1 < len(starts):
            end = min(end, starts[i + 1])
        for e in chord:
            e.end = end
        if end > s:
            out.append(chord)
    return out


def _trim_rh(chord: list[Ev], max_poly: int, max_span: int) -> list[Ev]:
    chord = sorted(chord, key=lambda e: e.pitch)

    def removable() -> Ev | None:
        return next((e for e in chord if e.role != "melody"), None)

    while len(chord) > max_poly or (chord[-1].pitch - chord[0].pitch > max_span):
        victim = removable()
        if victim is None:
            # Only melody notes remain: keep the top one.
            chord = chord[-1:]
            break
        chord.remove(victim)
    return chord


def _trim_lh(chord: list[Ev], max_poly: int, max_span: int) -> list[Ev]:
    chord = sorted(chord, key=lambda e: e.pitch)
    while len(chord) > 1 and (len(chord) > max_poly or chord[-1].pitch - chord[0].pitch > max_span):
        chord.pop()  # keep the bass, drop from the top
    return chord


def enforce(
    events: list[Ev], profile: Profile, range_lo: int, range_hi: int
) -> tuple[list[Ev], list[str]]:
    warnings: list[str] = []
    folded: list[Ev] = []
    dropped = 0
    for e in events:
        p = fold_into(e.pitch, max(range_lo, 21), min(range_hi, 108))
        if p is None:
            dropped += 1
            continue
        e.pitch = p
        folded.append(e)

    rh = [c for c in chord_stream([e for e in folded if e.hand == "rh"])]
    lh = [c for c in chord_stream([e for e in folded if e.hand == "lh"])]
    rh = [_trim_rh(c, profile.max_poly, profile.max_span) for c in rh]
    lh = [_trim_lh(c, profile.max_poly, profile.max_span) for c in lh]

    # Collision check against the right hand sounding at the same time.
    rh_notes = [e for c in rh for e in c]
    rh_notes.sort(key=lambda e: e.start)
    moved = 0
    for chord in lh:
        s, e_ = chord[0].start, chord[0].end
        sounding = [r.pitch for r in rh_notes if r.start < e_ and s < r.end]
        if not sounding:
            continue
        ceiling = min(sounding) - 1
        for n in list(chord):
            if n.pitch > ceiling:
                lower = n.pitch - 12
                if lower >= profile.lh_bass_range[0] - 7 and lower not in {m.pitch for m in chord}:
                    n.pitch = lower
                    moved += 1
                else:
                    chord.remove(n)
                    dropped += 1
        chord.sort(key=lambda x: x.pitch)
        chord[:] = _trim_lh(chord, profile.max_poly, profile.max_span) if chord else chord

    if dropped:
        warnings.append(f"playability: {dropped} note(s) removed to fit range or hand limits")
    if moved:
        warnings.append(
            f"playability: {moved} left-hand note(s) moved down to avoid the right hand"
        )
    out = [e for c in rh for e in c] + [e for c in lh for e in c]
    out.sort(key=lambda e: (e.start, e.hand, e.pitch))
    return out, warnings

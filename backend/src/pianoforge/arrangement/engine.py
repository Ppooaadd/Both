"""Arrangement engine: AnalysisIR + ArrangementParams -> ScoreIR.

Stages:
 1. key       written key and transposition (optional easy-key for beginners)
 2. timeline  analysis beats -> bar-aligned ticks, grid choice (straight/triplet)
 3. melody    right-hand line: quantise, simplify, fit register
 4. harmony   chord spans at the level's harmonic rhythm
 5. left hand accompaniment pattern + voice leading (+ pedal)
 6. texture   right-hand chord tones under the melody
 7. playable  range, polyphony, span and hand-collision limits
 8. finish    fingering, dynamics, chord symbols, sections, statistics
"""

from __future__ import annotations

import bisect
import itertools
import math
from collections import Counter

import numpy as np

from pianoforge.analysis.ir import AnalysisIR
from pianoforge.analysis.merge import BeatGrid
from pianoforge.arrangement.events import Ev
from pianoforge.arrangement.fingering import assign_fingering
from pianoforge.arrangement.harmony import ChordLookup, Span, chord_spans, slot_ticks
from pianoforge.arrangement.keys import target_key, transpose_chord
from pianoforge.arrangement.melody import build_melody, select_melody
from pianoforge.arrangement.params import ArrangementParams
from pianoforge.arrangement.patterns import PatternContext, generate_left_hand, resolve_pattern
from pianoforge.arrangement.playability import enforce
from pianoforge.arrangement.profiles import Profile, resolve_profile
from pianoforge.arrangement.score_ir import (
    TPQ,
    ChordSymbol,
    PedalSpan,
    ScoreIR,
    ScoreNote,
    SectionMark,
)
from pianoforge.arrangement.texture import harmonize
from pianoforge.arrangement.timeline import Timeline, build_timeline, choose_grid
from pianoforge.db.enums import Difficulty

NOTE_NAMES = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
GRID_LABELS = {TPQ: "1/4", TPQ // 2: "1/8", TPQ // 4: "1/16", TPQ // 3: "1/8t"}


class ArrangementError(ValueError):
    """The analysis does not contain enough material to arrange."""


def note_name(pitch: int) -> str:
    return f"{NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}"


def _bass_lookup(
    ir: AnalysisIR, tl: Timeline, shift: int
) -> tuple[list[int], list[int], list[int]]:
    track = ir.tracks.get("bass")
    if track is None or track.source == "chords":
        return [], [], []
    rows = sorted(
        (round(tl.to_ticks(n.start_beat)), round(tl.to_ticks(n.end_beat)), (n.pitch + shift) % 12)
        for n in track.notes
        if n.start_beat is not None and n.end_beat is not None
    )
    return [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows]


def _velocities(events: list[Ev]) -> None:
    """Melody forward, accompaniment back; mild downbeat accent in the left hand."""
    for e in events:
        if e.role == "melody":
            e.vel = int(np.clip(64 + (e.vel - 64) * 0.5, 60, 100))
        elif e.role == "harmony":
            e.vel = int(np.clip(e.vel * 0.7, 45, 80))
        elif e.role == "bass":
            e.vel = int(np.clip(e.vel, 55, 78))
        else:
            e.vel = int(np.clip(e.vel, 40, 70))


def _stats(
    events: list[Ev], tempo_bpm: float, total_ticks: int, grid: int, pattern: str, melody_from: str
) -> dict[str, float | int | str]:
    out: dict[str, float | int | str] = {
        "pattern": pattern,
        "grid": GRID_LABELS.get(grid, str(grid)),
        "melody_source": melody_from,
    }
    seconds = max(total_ticks * 60.0 / (tempo_bpm * TPQ), 1e-6)
    onsets = len({(e.hand, e.start) for e in events})
    for hand in ("rh", "lh"):
        hs = [e for e in events if e.hand == hand]
        by_start = Counter(e.start for e in hs)
        spans: dict[int, list[int]] = {}
        for e in hs:
            spans.setdefault(e.start, []).append(e.pitch)
        out[f"{hand}_notes"] = len(hs)
        out[f"{hand}_max_poly"] = max(by_start.values(), default=0)
        out[f"{hand}_max_span"] = max((max(v) - min(v) for v in spans.values()), default=0)
        if hs:
            out[f"{hand}_range"] = (
                f"{note_name(min(e.pitch for e in hs))}–{note_name(max(e.pitch for e in hs))}"
            )
    nps = onsets / seconds
    melody = sorted((e for e in events if e.role == "melody"), key=lambda e: e.start)
    leaps = [abs(b.pitch - a.pitch) for a, b in itertools.pairwise(melody)]
    mean_leap = float(np.mean(leaps)) if leaps else 0.0
    poly = max(int(out["rh_max_poly"]), int(out["lh_max_poly"]))
    span = max(int(out["rh_max_span"]), int(out["lh_max_span"]))
    fineness = math.log2(TPQ / grid) if grid in (TPQ, TPQ // 2, TPQ // 4) else 1.6
    score = (
        3.5 * min(nps / 8.0, 1.0)
        + 2.0 * min((poly - 1) / 4.0, 1.0)
        + 1.5 * min(span / 16.0, 1.0)
        + 1.5 * min(fineness / 2.0, 1.0)
        + 1.5 * min(mean_leap / 7.0, 1.0)
    )
    out["onsets_per_second"] = round(nps, 2)
    out["mean_melody_leap"] = round(mean_leap, 2)
    out["difficulty_score"] = round(min(score, 10.0), 1)
    return out


def _crop(
    events: list[Ev], spans: list[Span], bar: int, melody: list[Ev]
) -> tuple[list[Ev], list[Span], int, int]:
    """Trim bars before the first and after the last melody note. Returns shift in ticks."""
    if not melody:
        return events, spans, 0, 0
    first_bar = min(e.start for e in melody) // bar
    last_bar = max(e.end - 1 for e in melody) // bar
    lo, hi = first_bar * bar, (last_bar + 1) * bar
    kept = []
    for e in events:
        if e.end <= lo or e.start >= hi:
            continue
        e.start, e.end = max(e.start, lo) - lo, min(e.end, hi) - lo
        kept.append(e)
    new_spans = [
        Span(max(s.start, lo) - lo, min(s.end, hi) - lo, s.root, s.quality, s.bass)
        for s in spans
        if s.end > lo and s.start < hi
    ]
    return kept, new_spans, lo, last_bar - first_bar + 1


def performance_beats(
    beat_times: list[float], tempo_bpm: float, tempo_scale: float, timing: str
) -> list[float]:
    """Seconds of each score beat in the rendered performance, starting at 0.

    ``original`` replays the recording's own beat timing (tempo drift, rubato,
    tempo changes), scaled by ``tempo_scale``; ``steady`` is metronomic. A
    non-increasing beat map falls back to steady.
    """
    n = len(beat_times)
    steady = [round(k * 60.0 / tempo_bpm, 4) for k in range(n)]
    if timing != "original" or n < 2:
        return steady
    t = np.asarray(beat_times, dtype=np.float64)
    if np.any(np.diff(t) <= 0):
        return steady
    return [round(float(x), 4) for x in (t - t[0]) / tempo_scale]


def arrange(ir: AnalysisIR, params: ArrangementParams, title: str) -> ScoreIR:
    profile: Profile = resolve_profile(params)
    warnings: list[str] = []

    # 1. key --------------------------------------------------------------------
    key, shift = target_key(ir.key, params.transpose, params.simplify_key)
    if shift:
        warnings.append(f"transposed by {shift:+d} semitones to {key.name}")

    # 2. timeline ---------------------------------------------------------------
    tl = build_timeline(ir)
    bar = tl.bar_ticks
    source_notes, melody_from = select_melody(ir, params.melody_source)
    if not source_notes and not any(c.root is not None for c in ir.chords):
        raise ArrangementError("no melody or chords detected")
    grid = choose_grid(
        [tl.to_ticks(n.start_beat) for n in source_notes if n.start_beat is not None],
        profile.grid,
        profile.allow_triplets,
    )

    # 3. melody -----------------------------------------------------------------
    melody = build_melody(source_notes, tl, shift, profile, grid)
    if not melody:
        warnings.append("melody: none detected; accompaniment only")

    # 4. harmony ----------------------------------------------------------------
    chords = [transpose_chord(c, shift) for c in ir.chords]
    last_tick = max(
        [e.end for e in melody]
        + [
            round(tl.to_ticks(c.end_beat))
            for c in chords
            if c.end_beat is not None and c.root is not None
        ]
        + [bar]
    )
    measures = max(1, math.ceil(last_tick / bar))
    total = measures * bar
    spans = chord_spans(
        chords,
        tl,
        total,
        slot_ticks(profile.harmonic_slot_beats, tl.beats_per_bar),
        simplify=profile.difficulty == Difficulty.beginner,
    )

    # 5. left hand --------------------------------------------------------------
    starts, ends, pcs = _bass_lookup(ir, tl, shift)

    def bass_at(tick: int) -> int | None:
        i = bisect.bisect_right(starts, tick) - 1
        return pcs[i] if i >= 0 and starts[i] <= tick < ends[i] else None

    tempo = ir.tempo.bpm * params.tempo_scale
    ctx = PatternContext(
        profile=profile,
        beats_per_bar=tl.beats_per_bar,
        grid=grid,
        tempo_bpm=tempo,
        density=params.density,
        bass_at=bass_at,
    )
    pattern = resolve_pattern(params.left_hand_pattern, ctx)
    lh, pedal = generate_left_hand(spans, pattern, ctx)

    # 6. right-hand texture -----------------------------------------------------
    rh_extra = harmonize(melody, ChordLookup(spans), profile, tl.beats_per_bar)
    events = [*melody, *rh_extra, *lh]

    # Optional intro/outro trimming (bars without melody at either end).
    shift_ticks = 0
    if not params.include_intro_outro and melody:
        events, spans, shift_ticks, measures = _crop(events, spans, bar, melody)
        total = measures * bar
        pedal = [
            PedalSpan(start=max(p.start - shift_ticks, 0), end=min(p.end - shift_ticks, total))
            for p in pedal
            if p.end - shift_ticks > 0 and p.start - shift_ticks < total
        ]

    # 7. playability ------------------------------------------------------------
    events, play_warnings = enforce(events, profile, params.range_low, params.range_high)
    warnings.extend(play_warnings)

    # 8. finish -----------------------------------------------------------------
    _velocities(events)
    assign_fingering(events)
    notes = [
        ScoreNote(
            hand=e.hand,
            pitch=e.pitch,
            start=e.start,
            dur=e.dur,
            velocity=e.vel,
            role=e.role,
            finger=e.finger,
        )
        for e in events
        if e.dur > 0
    ]
    symbols = [
        ChordSymbol(start=s.start, root=s.root, quality=s.quality, bass=s.bass) for s in spans
    ]
    grid_beats = BeatGrid(ir.beats, ir.tempo.bpm)
    sections: list[SectionMark] = []
    for sec in ir.sections:
        tick = round(tl.to_ticks(grid_beats.to_beat(sec.start))) - shift_ticks
        tick = max(0, round(tick / bar) * bar)
        if tick < total and (not sections or sections[-1].start != tick):
            sections.append(SectionMark(start=tick, label=sec.label))
    beat_times = tl.beat_times(total // TPQ + 1 + shift_ticks // TPQ)[shift_ticks // TPQ :]
    performance = performance_beats(beat_times, tempo, params.tempo_scale, params.timing)

    return ScoreIR(
        title=title,
        difficulty=params.difficulty.value,
        tempo_bpm=round(tempo, 2),
        time_signature=(tl.beats_per_bar, 4),
        key=key,
        transpose=shift,
        grid=grid,
        measures=measures,
        notes=notes,
        chords=symbols,
        sections=sections,
        pedal=pedal,
        beat_times=beat_times,
        performance_beats=performance,
        timing=params.timing,
        swing=round(tl.swing, 3),
        show_fingering=profile.show_fingering,
        stats={
            **_stats(events, tempo, total, grid, pattern, melody_from),
            "swing": round(tl.swing, 3),
        },
        warnings=warnings,
    )

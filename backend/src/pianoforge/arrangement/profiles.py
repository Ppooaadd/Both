"""Difficulty profiles: every numeric constraint the engine enforces per level.

Values follow docs/architecture.md §6. User parameters (grid, pattern,
density, range) override or modulate these defaults in ``resolve_profile``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from pianoforge.arrangement.params import ArrangementParams
from pianoforge.arrangement.score_ir import TPQ
from pianoforge.db.enums import Difficulty

GRID_TICKS = {"1/4": TPQ, "1/8": TPQ // 2, "1/16": TPQ // 4, "1/8t": TPQ // 3}


@dataclass(frozen=True)
class Profile:
    difficulty: Difficulty
    grid: int  # finest onset grid in ticks
    allow_triplets: bool
    max_poly: int  # simultaneous notes per hand
    max_span: int  # semitones within one hand at one time
    rh_range: tuple[int, int]  # preferred melody register
    lh_bass_range: tuple[int, int]  # register for single bass notes
    lh_chord_range: tuple[int, int]  # register for LH chord voicings
    harmonic_slot_beats: int  # chord-change resolution in beats (4/4)
    rh_extra_voices: int  # harmony notes added under the melody
    octave_doubling: bool
    follow_bass_line: bool  # use transcribed bass instead of chord roots
    max_melody_leap: int  # larger leaps are folded by an octave
    min_melody_ticks: int  # shorter quantised notes are dropped (unless on a beat)
    default_patterns: tuple[str, ...]  # candidates for left_hand_pattern="auto"
    show_fingering: bool
    use_pedal: bool


BASE: dict[Difficulty, Profile] = {
    Difficulty.beginner: Profile(
        difficulty=Difficulty.beginner,
        grid=TPQ,
        allow_triplets=False,
        max_poly=2,
        max_span=7,
        rh_range=(60, 79),
        lh_bass_range=(43, 55),
        lh_chord_range=(43, 57),
        harmonic_slot_beats=2,
        rh_extra_voices=0,
        octave_doubling=False,
        follow_bass_line=False,
        max_melody_leap=9,
        min_melody_ticks=TPQ,
        default_patterns=("root", "block"),
        show_fingering=True,
        use_pedal=False,
    ),
    Difficulty.intermediate: Profile(
        difficulty=Difficulty.intermediate,
        grid=TPQ // 2,
        allow_triplets=False,
        max_poly=3,
        max_span=12,
        rh_range=(57, 84),
        lh_bass_range=(36, 52),
        lh_chord_range=(45, 62),
        harmonic_slot_beats=2,
        rh_extra_voices=1,
        octave_doubling=False,
        follow_bass_line=False,
        max_melody_leap=12,
        min_melody_ticks=TPQ // 2,
        default_patterns=("block", "alberti", "arpeggio"),
        show_fingering=True,
        use_pedal=True,
    ),
    Difficulty.advanced: Profile(
        difficulty=Difficulty.advanced,
        grid=TPQ // 4,
        allow_triplets=True,
        max_poly=5,
        max_span=16,
        rh_range=(55, 91),
        lh_bass_range=(29, 48),
        lh_chord_range=(45, 64),
        harmonic_slot_beats=1,
        rh_extra_voices=2,
        octave_doubling=True,
        follow_bass_line=True,
        max_melody_leap=19,
        min_melody_ticks=TPQ // 4,
        default_patterns=("arpeggio", "stride", "alberti"),
        show_fingering=False,
        use_pedal=True,
    ),
}


def resolve_profile(params: ArrangementParams) -> Profile:
    p = BASE[params.difficulty]
    if params.quantize_grid == "1/8t":
        p = replace(p, grid=GRID_TICKS["1/8t"], allow_triplets=True)
    elif params.quantize_grid != "auto":
        # Coarser than the level default is allowed; finer is not (keeps levels honest).
        p = replace(p, grid=max(GRID_TICKS[params.quantize_grid], p.grid))
    # Clamp registers into the user's allowed range.
    lo, hi = params.range_low, params.range_high

    def clamp(r: tuple[int, int]) -> tuple[int, int]:
        a, b = max(r[0], lo), min(r[1], hi)
        return (a, b) if b - a >= 12 else r

    return replace(
        p,
        rh_range=clamp(p.rh_range),
        lh_bass_range=clamp(p.lh_bass_range),
        lh_chord_range=clamp(p.lh_chord_range),
        rh_extra_voices=min(p.rh_extra_voices, round(p.rh_extra_voices * (0.5 + params.density))),
        octave_doubling=p.octave_doubling and params.density >= 0.5,
    )

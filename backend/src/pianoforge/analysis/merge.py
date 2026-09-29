"""Combine rhythm, tonal and transcription parts into one AnalysisIR.

Responsibilities:
* map every event onto the beat grid (fractional ``*_beat`` fields)
* reduce melody/bass to monophonic lines (skyline / floor)
* fold octave errors into each role's playable range
* synthesise a harmony track from chords when no polyphonic transcriber ran
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import numpy.typing as npt

from pianoforge.analysis.adapters._tonal import QUALITY_INTERVALS
from pianoforge.analysis.ir import (
    AnalysisIR,
    ChordSegment,
    NoteEvent,
    NoteRole,
    NoteTrack,
    StemInfo,
    TempoInfo,
)
from pianoforge.analysis.parts import RhythmPart, TonalPart, TranscriptionPart

ROLE_RANGE: dict[str, tuple[int, int]] = {
    "melody": (40, 96),  # E2..C7: low male voices keep their real octave
    "bass": (28, 60),  # E1..C4
    "harmony": (40, 84),  # E2..C6
}
MIN_NOTE_S: dict[str, float] = {"melody": 0.06, "bass": 0.08, "harmony": 0.08}
OVERLAP_TOLERANCE_S = 0.03
HARMONY_BASE = 52  # lowest note of synthesised close-position chords (E3)


class BeatGrid:
    """Seconds <-> fractional beat index with linear extrapolation beyond the ends."""

    def __init__(self, beats: Iterable[float], fallback_bpm: float) -> None:
        b = np.asarray(sorted(beats), dtype=np.float64)
        if b.size < 2:
            period = 60.0 / fallback_bpm
            b = np.array([0.0, period], dtype=np.float64)
        self.beats = b
        self._first_period = float(b[1] - b[0])
        self._last_period = float(b[-1] - b[-2])
        self._idx = np.arange(b.size, dtype=np.float64)

    def to_beat(self, t: float) -> float:
        b = self.beats
        if t <= b[0]:
            return float((t - b[0]) / self._first_period)
        if t >= b[-1]:
            return float(b.size - 1 + (t - b[-1]) / self._last_period)
        return float(np.interp(t, b, self._idx))


def _fold(pitch: int, lo: int, hi: int) -> int:
    while pitch < lo:
        pitch += 12
    while pitch > hi:
        pitch -= 12
    return pitch


def reduce_monophonic(notes: list[NoteEvent], prefer: str) -> list[NoteEvent]:
    """Skyline (prefer='high') or floor (prefer='low') reduction of overlapping notes."""
    ordered = sorted(notes, key=lambda n: (n.start, -n.pitch if prefer == "high" else n.pitch))
    out: list[NoteEvent] = []
    for n in ordered:
        if not out or n.start >= out[-1].end - OVERLAP_TOLERANCE_S:
            out.append(n)
            continue
        prev = out[-1]
        wins = n.pitch > prev.pitch if prefer == "high" else n.pitch < prev.pitch
        if wins:
            if n.start - prev.start >= 0.05:
                out[-1] = prev.model_copy(update={"end": n.start})
            else:
                out.pop()
            out.append(n)
        elif n.end > prev.end + 0.1:
            # Keep the audible tail of a longer, losing note.
            # The tail continues a sounding note: it has no attack of its own.
            out.append(n.model_copy(update={"start": prev.end, "attack": 0.0}))
    return out


def _overlap(a: NoteEvent, b: NoteEvent) -> float:
    return max(0.0, min(a.end, b.end) - max(a.start, b.start))


def fix_octaves(notes: list[NoteEvent], shift_cost: float = 4.0) -> list[NoteEvent]:
    """Undo octave-up transcription errors in a one-voice line.

    Viterbi over a per-note octave shift of 0 or -12: the cost is the melodic
    leap between consecutive notes plus ``shift_cost`` per shifted note, so a
    note is only moved down when that makes the line markedly smoother.
    """
    if len(notes) < 3:
        return notes
    shifts = (0, -12)
    pitches = np.array([n.pitch for n in notes], dtype=np.float64)
    cost = np.array([0.0, shift_cost])
    back = np.zeros((len(notes), 2), dtype=np.int64)
    for i in range(1, len(notes)):
        new = np.empty(2)
        for j, sj in enumerate(shifts):
            leaps = [
                cost[k] + abs((pitches[i] + sj) - (pitches[i - 1] + sk))
                for k, sk in enumerate(shifts)
            ]
            k = int(np.argmin(leaps))
            new[j] = leaps[k] + (shift_cost if sj else 0.0)
            back[i, j] = k
        cost = new
    j = int(np.argmin(cost))
    out = list(notes)
    for i in range(len(notes) - 1, -1, -1):
        if shifts[j]:
            out[i] = notes[i].model_copy(update={"pitch": notes[i].pitch + shifts[j]})
        j = int(back[i, j])
    return out


# A note start whose relative onset strength is below this has no audible attack.
NO_ATTACK = 0.45
CONTINUATION_GAP_S = 0.06
GLIDE_MAX_S = 0.15


def merge_continuations(notes: list[NoteEvent]) -> list[NoteEvent]:
    """Join notes that continue the previous one instead of starting a new note.

    Transcribers split a sustained sung note at vibrato dips and report short
    neighbour pitches during glides. A note is folded into its predecessor
    when it starts within ``CONTINUATION_GAP_S`` of it, has no attack
    (``attack`` below ``NO_ATTACK``) and either repeats the pitch or is a short
    (< ``GLIDE_MAX_S``) note within two semitones. Notes without attack data
    fall back to joining only very short same-pitch fragments.
    """
    out: list[NoteEvent] = []
    for n in sorted(notes, key=lambda x: x.start):
        prev = out[-1] if out else None
        if prev is not None and n.pitch == prev.pitch and n.start < prev.end:
            # Same pitch sounding twice at once (e.g. after octave correction).
            out[-1] = prev.model_copy(update={"end": max(prev.end, n.end)})
            continue
        if prev is None or not 0 <= n.start - prev.end <= CONTINUATION_GAP_S:
            out.append(n)
            continue
        dur = n.end - n.start
        if n.attack is None:
            joins = n.pitch == prev.pitch and min(dur, prev.end - prev.start) < 0.12
        else:
            weak = n.attack < NO_ATTACK
            joins = weak and (
                n.pitch == prev.pitch or (abs(n.pitch - prev.pitch) <= 2 and dur < GLIDE_MAX_S)
            )
        if joins:
            out[-1] = prev.model_copy(
                update={
                    "end": max(prev.end, n.end),
                    "confidence": max(prev.confidence, n.confidence),
                    "velocity": max(prev.velocity, n.velocity),
                }
            )
        else:
            out.append(n)
    return out


def melody_line(notes: list[NoteEvent]) -> list[NoteEvent]:
    """One-voice melody from polyphonic transcriber output.

    The top voice is taken (accompaniment bleeding into a vocal stem sits below
    the tune), split notes are joined, and octave-up errors are corrected
    against the line's own contour.
    """
    return merge_continuations(fix_octaves(reduce_monophonic(notes, prefer="high")))


def _clean(notes: list[NoteEvent], role: str) -> list[NoteEvent]:
    lo, hi = ROLE_RANGE[role]
    min_dur = MIN_NOTE_S[role]
    out = []
    for n in notes:
        if n.end - n.start < min_dur:
            continue
        pitch = _fold(n.pitch, lo, hi)
        out.append(n if pitch == n.pitch else n.model_copy(update={"pitch": pitch}))
    return out


def _dedupe_against(notes: list[NoteEvent], reference: list[NoteEvent]) -> list[NoteEvent]:
    """Drop harmony notes doubling a melody note (same pitch, overlapping in time)."""
    if not reference:
        return notes
    starts = np.array([r.start for r in reference])
    out = []
    for n in notes:
        i = int(np.searchsorted(starts, n.start))
        dup = False
        for r in reference[max(0, i - 3) : i + 3]:
            if r.pitch == n.pitch and r.start < n.end and n.start < r.end:
                dup = True
                break
        if not dup:
            out.append(n)
    return out


def harmony_from_chords(chords: list[ChordSegment]) -> list[NoteEvent]:
    out: list[NoteEvent] = []
    for c in chords:
        if c.root is None or c.quality == "N":
            continue
        base = HARMONY_BASE + ((c.root - HARMONY_BASE) % 12)
        for iv in QUALITY_INTERVALS[c.quality]:
            out.append(
                NoteEvent(
                    start=c.start,
                    end=c.end,
                    pitch=base + iv,
                    velocity=60,
                    confidence=c.confidence,
                )
            )
    return out


def _with_beats(notes: Iterable[NoteEvent], grid: BeatGrid) -> list[NoteEvent]:
    return [
        n.model_copy(
            update={
                "start_beat": round(grid.to_beat(n.start), 3),
                "end_beat": round(grid.to_beat(n.end), 3),
            }
        )
        for n in notes
    ]


def merge_analysis(
    *,
    pipeline_version: str,
    duration: float,
    sample_rate: int,
    separator_engine: str,
    stems: list[StemInfo],
    rhythm: RhythmPart,
    tonal: TonalPart,
    transcription: TranscriptionPart,
    extra_warnings: list[str] | None = None,
) -> AnalysisIR:
    grid = BeatGrid(rhythm.beats, rhythm.bpm)
    warnings = [*(extra_warnings or []), *rhythm.warnings, *tonal.warnings, *transcription.warnings]
    engines: dict[str, str] = {
        "separator": separator_engine,
        "beat_tracker": rhythm.engine,
        "key_detector": tonal.key_engine,
        "chord_recognizer": tonal.chord_engine,
    }

    tracks: dict[NoteRole, NoteTrack] = {}
    by_role = {t.role: t for t in transcription.tracks}

    melody_part = by_role.get("melody")
    melody: list[NoteEvent] = []
    if melody_part:
        melody = melody_line(_clean(melody_part.notes, "melody"))
        engines["transcriber.melody"] = melody_part.engine

    bass_part = by_role.get("bass")
    bass: list[NoteEvent] = []
    if bass_part:
        bass = reduce_monophonic(_clean(bass_part.notes, "bass"), prefer="low")
        engines["transcriber.bass"] = bass_part.engine
    if not bass:
        # Chord roots are a reasonable bass line when transcription found nothing.
        bass = [
            NoteEvent(
                start=c.start,
                end=c.end,
                pitch=_fold(
                    36 + ((c.bass if c.bass is not None else c.root) or 0), *ROLE_RANGE["bass"]
                ),
                velocity=70,
                confidence=c.confidence,
            )
            for c in tonal.chords
            if c.root is not None
        ]
        if bass:
            warnings.append("bass: derived from chord roots")

    harmony_part = by_role.get("harmony")
    harmony: list[NoteEvent] = []
    harmony_engine = "chords"
    harmony_source = "chords"
    if harmony_part and harmony_part.polyphonic and harmony_part.notes:
        harmony = _dedupe_against(_clean(harmony_part.notes, "harmony"), melody)
        harmony_engine, harmony_source = harmony_part.engine, harmony_part.source
    if not harmony:
        harmony = harmony_from_chords(tonal.chords)
        if harmony:
            warnings.append("harmony: derived from recognised chords")
    engines["transcriber.harmony"] = harmony_engine

    if not melody and harmony:
        melody = reduce_monophonic(_clean(harmony, "melody"), prefer="high")
        warnings.append("melody: no melodic line detected; using top voice of harmony")

    tracks["melody"] = NoteTrack(
        role="melody",
        source=melody_part.source if melody_part else "harmony",
        engine=engines.get("transcriber.melody", harmony_engine),
        notes=_with_beats(melody, grid),
    )
    tracks["bass"] = NoteTrack(
        role="bass",
        source=bass_part.source if bass_part and bass_part.notes else "chords",
        engine=engines.get("transcriber.bass", "chords"),
        notes=_with_beats(bass, grid),
    )
    tracks["harmony"] = NoteTrack(
        role="harmony",
        source=harmony_source,
        engine=harmony_engine,
        notes=_with_beats(harmony, grid),
    )

    chords = [
        c.model_copy(
            update={
                "start_beat": round(grid.to_beat(c.start), 3),
                "end_beat": round(grid.to_beat(c.end), 3),
            }
        )
        for c in tonal.chords
    ]

    return AnalysisIR(
        pipeline_version=pipeline_version,
        duration=duration,
        sample_rate=sample_rate,
        engines=engines,
        tempo=TempoInfo(bpm=rhythm.bpm, confidence=rhythm.confidence, curve=rhythm.tempo_curve),
        time_signature=rhythm.time_signature,
        beats=[round(b, 4) for b in rhythm.beats],
        beat_loudness_db=rhythm.beat_loudness_db,
        downbeats=[round(b, 4) for b in rhythm.downbeats],
        key=tonal.key,
        chords=chords,
        sections=tonal.sections,
        tracks=tracks,
        stems=stems,
        warnings=sorted(set(warnings), key=warnings.index),
    )


def as_f64(values: Iterable[float]) -> npt.NDArray[np.float64]:
    return np.asarray(list(values), dtype=np.float64)

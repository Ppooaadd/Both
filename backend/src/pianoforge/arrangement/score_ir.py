"""ScoreIR: engine-independent piano score, the single source for every export.

Positions are integer ticks at ``TPQ`` ticks per quarter note. Each hand is a
*chord stream*: events never overlap within a hand, and notes sharing an
onset share a duration. That invariant keeps MusicXML to one voice per staff
and makes the piano roll trivially renderable.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pianoforge.analysis.ir import PITCH_CLASS_NAMES, ChordQuality

TPQ = 480
SCORE_SCHEMA_VERSION = 2

Hand = Literal["rh", "lh"]
NoteRole = Literal["melody", "harmony", "bass", "accomp"]


def swing_map(frac: float, swing: float) -> float:
    """Written position within a beat -> played position (0.5 -> ``swing``)."""
    if frac < 0.5:
        return frac * 2 * swing
    return swing + (frac - 0.5) * 2 * (1 - swing)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ScoreNote(_Frozen):
    hand: Hand
    pitch: int = Field(ge=21, le=108)
    start: int = Field(ge=0)
    dur: int = Field(gt=0)
    velocity: int = Field(ge=1, le=127)
    role: NoteRole
    finger: int | None = Field(default=None, ge=1, le=5)

    @property
    def end(self) -> int:
        return self.start + self.dur


class ChordSymbol(_Frozen):
    start: int = Field(ge=0)
    root: int = Field(ge=0, le=11)
    quality: ChordQuality
    bass: int | None = Field(default=None, ge=0, le=11)

    @property
    def label(self) -> str:
        suffix = {"maj": "", "min": "m", "dim": "dim", "aug": "aug", "sus4": "sus4",
                  "7": "7", "maj7": "maj7", "min7": "m7", "N": ""}[self.quality]  # fmt: skip
        text = PITCH_CLASS_NAMES[self.root] + suffix
        if self.bass is not None and self.bass != self.root:
            text += "/" + PITCH_CLASS_NAMES[self.bass]
        return text


class SectionMark(_Frozen):
    start: int = Field(ge=0)
    label: str


class PedalSpan(_Frozen):
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class ScoreKey(_Frozen):
    tonic: int = Field(ge=0, le=11)
    mode: Literal["major", "minor"]
    fifths: int = Field(ge=-7, le=7)

    @property
    def name(self) -> str:
        return f"{PITCH_CLASS_NAMES[self.tonic]} {self.mode}"


class ScoreIR(_Frozen):
    schema_version: int = SCORE_SCHEMA_VERSION
    title: str
    difficulty: Literal["beginner", "intermediate", "advanced"]
    tpq: int = TPQ
    tempo_bpm: float = Field(gt=0)
    time_signature: tuple[int, int]
    key: ScoreKey
    transpose: int  # semitones applied relative to the source recording
    grid: int  # quantisation step in ticks
    measures: int = Field(ge=1)
    notes: list[ScoreNote]
    chords: list[ChordSymbol]
    sections: list[SectionMark]
    pedal: list[PedalSpan]
    # Source-audio time (s) of every score beat, for syncing with the original.
    beat_times: list[float]
    # Performance time (s from the start of the rendered audio) of every score
    # beat. Empty (schema v1) means a steady tempo_bpm.
    performance_beats: list[float] = Field(default_factory=list)
    timing: Literal["original", "steady"] = "steady"
    # Played position of written off-beat eighths (0.5 = straight).
    swing: float = Field(default=0.5, ge=0.5, lt=0.8)
    show_fingering: bool
    stats: dict[str, float | int | str]
    warnings: list[str] = Field(default_factory=list)

    @property
    def measure_ticks(self) -> int:
        num, den = self.time_signature
        return num * self.tpq * 4 // den

    @property
    def total_ticks(self) -> int:
        return self.measures * self.measure_ticks

    def seconds_per_tick(self) -> float:
        """Average seconds per tick (the notated tempo)."""
        return 60.0 / (self.tempo_bpm * self.tpq)

    def performed_tick(self, tick: float) -> float:
        """Tick with swing applied to off-beats (the played, not written, position)."""
        if self.swing == 0.5:
            return tick
        beat, frac = divmod(tick / self.tpq, 1.0)
        return (beat + swing_map(frac, self.swing)) * self.tpq

    def tick_to_seconds(self, tick: float) -> float:
        """Performance time of a written tick: swing, then the beat map."""
        pb = self.performance_beats
        tick = self.performed_tick(tick)
        if len(pb) < 2:
            return tick * self.seconds_per_tick()
        beat = tick / self.tpq
        last = len(pb) - 1
        if beat <= 0:
            return beat * (pb[1] - pb[0])
        if beat >= last:
            return pb[last] + (beat - last) * (pb[last] - pb[last - 1])
        i = int(beat)
        return pb[i] + (beat - i) * (pb[i + 1] - pb[i])

    @property
    def duration_s(self) -> float:
        return self.tick_to_seconds(self.total_ticks)

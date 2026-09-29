"""AnalysisIR: the canonical, engine-independent analysis result.

Everything downstream (arrangement, UI chord lane, piano roll overlay) reads
this model only. Times are in seconds; ``*_beat`` fields are fractional beat
indices on the detected beat grid (beat 0 = first detected beat).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

IR_SCHEMA_VERSION = 1

PITCH_CLASS_NAMES = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")

ChordQuality = Literal["maj", "min", "dim", "aug", "sus4", "7", "maj7", "min7", "N"]
NoteRole = Literal["melody", "bass", "harmony"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NoteEvent(_Frozen):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    pitch: int = Field(ge=0, le=127)  # MIDI note number
    velocity: int = Field(ge=1, le=127)
    confidence: float = Field(ge=0, le=1, default=1.0)
    start_beat: float | None = None
    end_beat: float | None = None
    # Onset strength of the source audio at ``start`` relative to its local
    # level (about 1 = a typical attack, below 0.4 = no audible re-attack).
    attack: float | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start


class TempoInfo(_Frozen):
    bpm: float = Field(gt=0)
    confidence: float = Field(ge=0, le=1)
    # (time_sec, local_bpm) samples; lets arrangement follow rubato.
    curve: list[tuple[float, float]] = Field(default_factory=list)


class TimeSignature(_Frozen):
    numerator: int = Field(ge=2, le=12)
    denominator: int = Field(default=4)

    def __str__(self) -> str:
        return f"{self.numerator}/{self.denominator}"


class KeyInfo(_Frozen):
    tonic: int = Field(ge=0, le=11)
    mode: Literal["major", "minor"]
    confidence: float = Field(ge=0, le=1)
    # Correlation per candidate, e.g. {"C:major": 0.82, ...}; top 5 only.
    candidates: dict[str, float] = Field(default_factory=dict)

    @property
    def name(self) -> str:
        return f"{PITCH_CLASS_NAMES[self.tonic]} {self.mode}"


class ChordSegment(_Frozen):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    root: int | None = Field(default=None, ge=0, le=11)  # None for "N" (no chord)
    quality: ChordQuality
    bass: int | None = Field(default=None, ge=0, le=11)  # slash-chord bass pitch class
    confidence: float = Field(ge=0, le=1)
    start_beat: float | None = None
    end_beat: float | None = None

    @property
    def label(self) -> str:
        if self.root is None or self.quality == "N":
            return "N"
        suffix = {"maj": "", "min": "m", "dim": "dim", "aug": "aug", "sus4": "sus4",
                  "7": "7", "maj7": "maj7", "min7": "m7"}[self.quality]  # fmt: skip
        text = PITCH_CLASS_NAMES[self.root] + suffix
        if self.bass is not None and self.bass != self.root:
            text += "/" + PITCH_CLASS_NAMES[self.bass]
        return text


class Section(_Frozen):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    label: str  # "A", "B", ... identical letters = similar material


class StemInfo(_Frozen):
    kind: Literal["vocals", "drums", "bass", "other", "mix"]
    engine: str
    rms_db: float
    storage_key: str


class NoteTrack(_Frozen):
    role: NoteRole
    source: str  # stem the notes were transcribed from
    engine: str
    notes: list[NoteEvent]


class AnalysisIR(_Frozen):
    schema_version: int = IR_SCHEMA_VERSION
    pipeline_version: str
    duration: float = Field(gt=0)
    sample_rate: int
    engines: dict[str, str]  # role -> "engine@version"
    tempo: TempoInfo
    time_signature: TimeSignature
    beats: list[float]
    downbeats: list[float]
    key: KeyInfo
    chords: list[ChordSegment]
    sections: list[Section]
    tracks: dict[NoteRole, NoteTrack]
    stems: list[StemInfo]
    warnings: list[str] = Field(default_factory=list)

    def summary(self) -> dict[str, object]:
        """Compact metadata persisted in ``analyses.summary``."""
        chord_counts: dict[str, float] = {}
        for c in self.chords:
            chord_counts[c.label] = chord_counts.get(c.label, 0.0) + (c.end - c.start)
        top = sorted(chord_counts.items(), key=lambda kv: kv[1], reverse=True)[:8]
        return {
            "key": self.key.name,
            "tempo_bpm": round(self.tempo.bpm, 1),
            "time_signature": str(self.time_signature),
            "duration": round(self.duration, 2),
            "bars": max(len(self.downbeats), 1),
            "top_chords": [{"label": k, "seconds": round(v, 2)} for k, v in top],
            "sections": [s.label for s in self.sections],
            "note_counts": {role: len(t.notes) for role, t in self.tracks.items()},
            "engines": self.engines,
            "warnings": self.warnings,
        }

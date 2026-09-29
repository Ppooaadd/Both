"""Intermediate results exchanged between pipeline tasks (stored as gzip JSON in S3)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from pianoforge.analysis.ir import (
    ChordSegment,
    KeyInfo,
    NoteEvent,
    NoteRole,
    Section,
    TimeSignature,
)


class _Part(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RhythmPart(_Part):
    engine: str
    bpm: float
    beats: list[float]
    downbeats: list[float]
    time_signature: TimeSignature
    confidence: float
    tempo_curve: list[tuple[float, float]]
    # Mix loudness (dB below the song's loud level) from each beat to the next.
    beat_loudness_db: list[float] = []
    warnings: list[str] = []


class TonalPart(_Part):
    key_engine: str
    chord_engine: str
    key: KeyInfo
    chords: list[ChordSegment]
    sections: list[Section]
    warnings: list[str] = []


class TrackPart(_Part):
    role: NoteRole
    source: str
    engine: str
    polyphonic: bool
    notes: list[NoteEvent]


class TranscriptionPart(_Part):
    tracks: list[TrackPart]
    warnings: list[str] = []

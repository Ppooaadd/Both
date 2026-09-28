"""Adapter interfaces for every replaceable analysis engine.

Each adapter declares ``name``/``version`` and a cheap ``is_available()`` that
checks imports and resources without loading models. Heavy initialisation
happens lazily on first use and is cached per worker process.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import ClassVar

import numpy as np
import numpy.typing as npt

from pianoforge.analysis.ir import ChordSegment, KeyInfo, NoteEvent, NoteRole, TimeSignature
from pianoforge.audio.buffer import AudioBuffer

FloatArray = npt.NDArray[np.float32]
ProgressFn = Callable[[float], None]  # fraction 0..1 within the current stage


def _noop(_: float) -> None:
    return None


class Interrupted(Exception):
    """Raised (usually from a progress callback) to abort work.

    Adapter chains re-raise it instead of falling back to the next engine.
    """


class Adapter(ABC):
    role: ClassVar[str]
    name: ClassVar[str]
    version: ClassVar[str] = "1"

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """True when dependencies are importable. Must not load models."""

    @property
    def engine_id(self) -> str:
        return f"{self.name}@{self.version}"


# ---------------------------------------------------------------- separation
STEM_KINDS = ("vocals", "drums", "bass", "other")


@dataclass
class SeparationResult:
    stems: dict[str, AudioBuffer]  # subset of STEM_KINDS, or {"mix": ...} for passthrough
    engine: str
    warnings: list[str] = field(default_factory=list)


class SourceSeparator(Adapter):
    role: ClassVar[str] = "separator"

    @abstractmethod
    def separate(self, audio: AudioBuffer, progress: ProgressFn = _noop) -> SeparationResult: ...


# ------------------------------------------------------------- transcription
@dataclass(frozen=True)
class TranscriptionRequest:
    audio: AudioBuffer
    role: NoteRole
    min_hz: float
    max_hz: float


class NoteTranscriber(Adapter):
    role: ClassVar[str] = "transcriber"
    polyphonic: ClassVar[bool]

    @abstractmethod
    def transcribe(
        self, request: TranscriptionRequest, progress: ProgressFn = _noop
    ) -> list[NoteEvent]: ...


# ------------------------------------------------------------------- rhythm
@dataclass(frozen=True)
class BeatResult:
    bpm: float
    beats: FloatArray  # seconds
    downbeats: FloatArray  # seconds, subset of beats
    time_signature: TimeSignature
    confidence: float
    tempo_curve: list[tuple[float, float]]


class BeatTracker(Adapter):
    role: ClassVar[str] = "beat_tracker"

    @abstractmethod
    def track(
        self, mix: AudioBuffer, stems: Mapping[str, AudioBuffer], progress: ProgressFn = _noop
    ) -> BeatResult: ...


# -------------------------------------------------------------------- tonal
@dataclass(frozen=True)
class TonalInput:
    harmonic: AudioBuffer  # mix of pitched stems (other + bass [+ vocals])
    bass: AudioBuffer | None
    beats: FloatArray
    sample_rate: int


class KeyDetector(Adapter):
    role: ClassVar[str] = "key_detector"

    @abstractmethod
    def detect(self, data: TonalInput) -> KeyInfo: ...


class ChordRecognizer(Adapter):
    role: ClassVar[str] = "chord_recognizer"

    @abstractmethod
    def recognize(
        self, data: TonalInput, key: KeyInfo, progress: ProgressFn = _noop
    ) -> list[ChordSegment]: ...

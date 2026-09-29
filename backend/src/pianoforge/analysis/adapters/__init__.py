"""Adapter catalogue. Order here is irrelevant; settings define fallback order."""

from pianoforge.analysis.adapters.beats_beat_this import BeatThisTracker
from pianoforge.analysis.adapters.beats_fixed import FixedBeatTracker
from pianoforge.analysis.adapters.beats_librosa import LibrosaBeatTracker
from pianoforge.analysis.adapters.beats_madmom import MadmomBeatTracker
from pianoforge.analysis.adapters.chords_hmm import HmmChordRecognizer, TemplateChordRecognizer
from pianoforge.analysis.adapters.key_krumhansl import KrumhanslKeyDetector
from pianoforge.analysis.adapters.separation_demucs import DemucsSeparator
from pianoforge.analysis.adapters.separation_hpss import HpssSeparator
from pianoforge.analysis.adapters.separation_passthrough import PassthroughSeparator
from pianoforge.analysis.adapters.transcribe_basic_pitch import BasicPitchTranscriber
from pianoforge.analysis.adapters.transcribe_crepe import CrepeTranscriber
from pianoforge.analysis.adapters.transcribe_pyin import PyinTranscriber
from pianoforge.analysis.interfaces import (
    BeatTracker,
    ChordRecognizer,
    KeyDetector,
    NoteTranscriber,
    SourceSeparator,
)

SEPARATORS: list[type[SourceSeparator]] = [DemucsSeparator, HpssSeparator, PassthroughSeparator]
TRANSCRIBERS: list[type[NoteTranscriber]] = [BasicPitchTranscriber, PyinTranscriber]
# Sung melodies (vocal stem): monophonic pitch trackers first.
VOCAL_TRANSCRIBERS: list[type[NoteTranscriber]] = [
    CrepeTranscriber,
    BasicPitchTranscriber,
    PyinTranscriber,
]
BEAT_TRACKERS: list[type[BeatTracker]] = [
    BeatThisTracker,
    MadmomBeatTracker,
    LibrosaBeatTracker,
    FixedBeatTracker,
]
KEY_DETECTORS: list[type[KeyDetector]] = [KrumhanslKeyDetector]
CHORD_RECOGNIZERS: list[type[ChordRecognizer]] = [HmmChordRecognizer, TemplateChordRecognizer]

__all__ = [
    "BEAT_TRACKERS",
    "CHORD_RECOGNIZERS",
    "KEY_DETECTORS",
    "SEPARATORS",
    "TRANSCRIBERS",
    "VOCAL_TRANSCRIBERS",
    "BasicPitchTranscriber",
    "BeatThisTracker",
    "CrepeTranscriber",
    "DemucsSeparator",
    "FixedBeatTracker",
    "HmmChordRecognizer",
    "HpssSeparator",
    "KrumhanslKeyDetector",
    "LibrosaBeatTracker",
    "MadmomBeatTracker",
    "PassthroughSeparator",
    "PyinTranscriber",
    "TemplateChordRecognizer",
]

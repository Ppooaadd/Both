from __future__ import annotations

import numpy as np
import pytest

from pianoforge.analysis.adapters.beats_librosa import LibrosaBeatTracker
from pianoforge.analysis.adapters.chords_hmm import HmmChordRecognizer, TemplateChordRecognizer
from pianoforge.analysis.adapters.key_krumhansl import KrumhanslKeyDetector
from pianoforge.analysis.adapters.separation_hpss import HpssSeparator
from pianoforge.analysis.adapters.transcribe_pyin import PyinTranscriber
from pianoforge.analysis.interfaces import TonalInput, TranscriptionRequest
from pianoforge.analysis.ir import ChordSegment, KeyInfo
from pianoforge.analysis.service import harmonic_source
from tests.synth import Song, render_song


@pytest.fixture(scope="module")
def song() -> Song:
    return render_song(bpm=100.0, repeats=4)


def _chord_accuracy(pred: list[ChordSegment], song: Song) -> float:
    """Fraction of ground-truth time labelled with the right root+triad type."""
    hit = total = 0.0
    step = 0.05
    for start, end, root, quality in song.chord_labels:
        t = start + step / 2
        while t < end:
            total += step
            for c in pred:
                if c.start <= t < c.end:
                    base = {"7": "maj", "maj7": "maj", "sus4": "maj", "aug": "maj",
                            "min7": "min", "dim": "min"}.get(c.quality, c.quality)  # fmt: skip
                    if c.root == root and base == quality:
                        hit += step
                    break
            t += step
    return hit / total


@pytest.mark.parametrize("bpm", [87.0, 100.0, 128.0])
def test_beat_tracker_tempo_and_meter(bpm: float) -> None:
    song = render_song(bpm=bpm, repeats=4)
    res = LibrosaBeatTracker().track(song.mix, song.stems)
    assert res.bpm == pytest.approx(song.bpm, rel=0.03)
    assert res.time_signature.numerator == 4
    # Detected beats land on true beats.
    errors = [np.min(np.abs(song.beats - b)) for b in res.beats[2:-2]]
    assert float(np.median(errors)) < 0.05
    # Downbeats fall on bar starts (every 4th true beat).
    bar_starts = song.beats[::4]
    db_err = [np.min(np.abs(bar_starts - d)) for d in res.downbeats[1:-1]]
    assert float(np.median(db_err)) < 0.08
    assert len(res.beats) == len(song.beats)


def test_beat_tracker_octave_ambiguity_is_bounded() -> None:
    """Known DSP-fallback limit: very slow/fast songs may be tracked at 2x or 0.5x."""
    song = render_song(bpm=72.0, repeats=3)
    res = LibrosaBeatTracker().track(song.mix, song.stems)
    ratio = res.bpm / 72.0
    assert min(abs(ratio - r) for r in (0.5, 1.0, 2.0)) < 0.02


def test_key_detection_c_major(song: Song) -> None:
    data = TonalInput(
        harmonic=harmonic_source(song.mix, song.stems),
        bass=song.stems["bass"],
        beats=song.beats,
        sample_rate=22_050,
    )
    key = KrumhanslKeyDetector().detect(data)
    assert (key.tonic, key.mode) == (0, "major")
    assert 0.0 < key.confidence <= 1.0


@pytest.mark.parametrize("recognizer", [HmmChordRecognizer, TemplateChordRecognizer])
def test_chord_recognition(song: Song, recognizer: type) -> None:
    data = TonalInput(
        harmonic=harmonic_source(song.mix, song.stems),
        bass=song.stems["bass"],
        beats=song.beats,
        sample_rate=22_050,
    )
    key = KeyInfo(tonic=0, mode="major", confidence=0.8)
    chords = recognizer().recognize(data, key)
    assert _chord_accuracy(chords, song) >= 0.8
    labels = {c.label for c in chords}
    assert {"C", "Am", "F", "G"} & labels


def test_pyin_melody(song: Song) -> None:
    req = TranscriptionRequest(audio=song.stems["vocals"], role="melody", min_hz=80, max_hz=2000)
    notes = PyinTranscriber().transcribe(req)
    assert len(notes) >= len(song.melody) * 0.7
    correct = 0
    for start, _end, pitch in song.melody:
        match = [n for n in notes if abs(n.start - start) < 0.08]
        if match and match[0].pitch == pitch:
            correct += 1
    assert correct / len(song.melody) >= 0.8


def test_pyin_harmony_is_empty(song: Song) -> None:
    req = TranscriptionRequest(audio=song.stems["other"], role="harmony", min_hz=60, max_hz=2000)
    assert PyinTranscriber().transcribe(req) == []


def test_hpss_separator_shapes(song: Song) -> None:
    res = HpssSeparator().separate(song.mix)
    assert set(res.stems) == {"vocals", "drums", "bass", "other"}
    for buf in res.stems.values():
        assert buf.frames == pytest.approx(song.mix.resampled(22_050).frames, abs=1)
    # Percussive stem should carry most drum energy relative to the bass stem.
    assert res.stems["drums"].rms_db() > res.stems["bass"].rms_db() - 20

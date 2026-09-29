from __future__ import annotations

import itertools
from typing import ClassVar

import pytest

from pianoforge.analysis.interfaces import SeparationResult, SourceSeparator
from pianoforge.analysis.ir import ChordSegment, KeyInfo, NoteEvent, StemInfo, TimeSignature
from pianoforge.analysis.merge import (
    BeatGrid,
    harmony_from_chords,
    merge_analysis,
    reduce_monophonic,
)
from pianoforge.analysis.parts import RhythmPart, TonalPart, TrackPart, TranscriptionPart
from pianoforge.analysis.registry import AdapterChain, AdapterRegistry, NoAdapterAvailable
from pianoforge.audio.buffer import AudioBuffer
from pianoforge.config import Settings


class _Missing(SourceSeparator):
    name: ClassVar[str] = "missing"

    @classmethod
    def is_available(cls) -> bool:
        return False

    def separate(self, audio, progress=lambda _: None):  # type: ignore[no-untyped-def]
        raise AssertionError("must not be called")


class _Broken(SourceSeparator):
    name: ClassVar[str] = "broken"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def separate(self, audio, progress=lambda _: None):  # type: ignore[no-untyped-def]
        raise MemoryError("CUDA out of memory")


class _Works(SourceSeparator):
    name: ClassVar[str] = "works"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def separate(self, audio, progress=lambda _: None):  # type: ignore[no-untyped-def]
        return SeparationResult(stems={"mix": audio}, engine=self.engine_id)


def _buf() -> AudioBuffer:
    return AudioBuffer.from_mono([0.0] * 100, 22_050)


def test_chain_skips_unavailable_and_failed_adapters() -> None:
    chain = AdapterChain("separator", [_Missing, _Broken, _Works], ["missing", "broken", "works"])
    out = chain.run(lambda a: a.separate(_buf()))
    assert out.engine == "works@1"
    assert out.adapter_cls is _Works
    assert out.degraded is True
    assert any("missing not installed" in w for w in out.warnings)
    assert any("broken failed (MemoryError)" in w for w in out.warnings)


def test_chain_primary_not_degraded() -> None:
    chain = AdapterChain("separator", [_Works, _Broken], ["works", "broken"])
    out = chain.run(lambda a: a.separate(_buf()))
    assert out.degraded is False


def test_chain_all_failed() -> None:
    chain = AdapterChain("separator", [_Missing, _Broken], ["missing", "broken"])
    with pytest.raises(NoAdapterAvailable):
        chain.run(lambda a: a.separate(_buf()))


def test_chain_rejects_unknown_names() -> None:
    with pytest.raises(ValueError, match="unknown separator"):
        AdapterChain("separator", [_Works], ["nope"])


def test_registry_from_settings_csv_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PF_SEPARATOR_CHAIN", "hpss,passthrough")
    monkeypatch.setenv("PF_CORS_ORIGINS", '["https://a.example","https://b.example"]')
    s = Settings()
    assert s.separator_chain == ["hpss", "passthrough"]
    assert s.cors_origins == ["https://a.example", "https://b.example"]
    reg = AdapterRegistry(s)
    report = reg.report()
    assert [e["name"] for e in report["separator"]] == ["hpss", "passthrough"]
    assert reg.separator.primary().name == "hpss"


def _n(start: float, end: float, pitch: int, vel: int = 80) -> NoteEvent:
    return NoteEvent(start=start, end=end, pitch=pitch, velocity=vel)


def test_reduce_monophonic_skyline_and_floor() -> None:
    notes = [_n(0.0, 1.0, 60), _n(0.0, 1.0, 67), _n(0.5, 1.5, 64), _n(2.0, 2.5, 62)]
    high = reduce_monophonic(notes, prefer="high")
    assert [n.pitch for n in high] == [67, 64, 62]
    # Losing note with a longer tail keeps the tail after the winner ends.
    assert high[1].start == pytest.approx(1.0)
    low = reduce_monophonic(notes, prefer="low")
    assert low[0].pitch == 60
    for a, b in itertools.pairwise(low):
        assert b.start >= a.end - 0.03


def test_beat_grid_mapping_and_extrapolation() -> None:
    grid = BeatGrid([1.0, 1.5, 2.0, 2.5], fallback_bpm=120)
    assert grid.to_beat(1.0) == pytest.approx(0.0)
    assert grid.to_beat(1.75) == pytest.approx(1.5)
    assert grid.to_beat(0.5) == pytest.approx(-1.0)
    assert grid.to_beat(3.0) == pytest.approx(4.0)


def test_harmony_from_chords_close_position() -> None:
    chords = [
        ChordSegment(start=0, end=2, root=0, quality="maj", confidence=0.9),
        ChordSegment(start=2, end=4, root=9, quality="min7", confidence=0.9),
        ChordSegment(start=4, end=5, quality="N", confidence=0.9),
    ]
    notes = harmony_from_chords(chords)
    c = sorted(n.pitch for n in notes if n.start == 0)
    am7 = sorted(n.pitch for n in notes if n.start == 2)
    assert c == [60, 64, 67]
    assert am7 == [57, 60, 64, 67]
    assert all(n.start < 4 for n in notes)


def test_merge_derives_missing_tracks_and_sets_beats() -> None:
    rhythm = RhythmPart(
        engine="librosa@x",
        bpm=120.0,
        beats=[0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
        downbeats=[0.0, 2.0],
        time_signature=TimeSignature(numerator=4),
        confidence=0.9,
        tempo_curve=[],
    )
    tonal = TonalPart(
        key_engine="krumhansl@1",
        chord_engine="hmm@1",
        key=KeyInfo(tonic=0, mode="major", confidence=0.8),
        chords=[
            ChordSegment(start=0, end=2, root=0, quality="maj", confidence=0.9),
            ChordSegment(start=2, end=4, root=7, quality="maj", confidence=0.8),
        ],
        sections=[],
    )
    transcription = TranscriptionPart(
        tracks=[
            TrackPart(
                role="melody",
                source="vocals",
                engine="pyin@1",
                polyphonic=False,
                # 40 is below melody range and must be folded up by octaves.
                notes=[_n(0.0, 0.5, 72), _n(0.5, 1.0, 28), _n(1.0, 1.01, 74)],
            ),
            TrackPart(role="bass", source="bass", engine="pyin@1", polyphonic=False, notes=[]),
            TrackPart(role="harmony", source="other", engine="pyin@1", polyphonic=False, notes=[]),
        ]
    )
    ir = merge_analysis(
        pipeline_version="test",
        duration=4.0,
        sample_rate=22_050,
        separator_engine="hpss@1",
        stems=[StemInfo(kind="mix", engine="passthrough@1", rms_db=-20, storage_key="k")],
        rhythm=rhythm,
        tonal=tonal,
        transcription=transcription,
    )
    melody = ir.tracks["melody"].notes
    assert [n.pitch for n in melody] == [72, 40]  # 28 folded to 40 (E2); 10 ms note dropped
    assert melody[1].start_beat == pytest.approx(1.0)
    assert [n.pitch for n in ir.tracks["bass"].notes] == [36, 43]
    assert ir.tracks["harmony"].source == "chords"
    assert ir.chords[1].start_beat == pytest.approx(4.0)
    assert "harmony: derived from recognised chords" in ir.warnings
    summary = ir.summary()
    assert summary["key"] == "C major"
    assert summary["bars"] == 2


def test_audio_validation_error_survives_celery_serialization() -> None:
    from pianoforge.audio.probe import AudioValidationError

    exc = AudioValidationError("too_long", "오디오 길이는 최대 10분까지 지원합니다.")
    rebuilt = type(exc)(*exc.args)
    assert (rebuilt.code, rebuilt.message) == (exc.code, exc.message)


def test_chain_propagates_interrupts_without_fallback() -> None:
    from pianoforge.analysis.interfaces import Interrupted
    from pianoforge.analysis.registry import register_propagating

    class SoftLimit(Exception):
        pass

    register_propagating(SoftLimit)
    chain = AdapterChain("separator", [_Works, _Broken], ["works", "broken"])

    for exc_type in (Interrupted, SoftLimit):
        calls: list[str] = []

        def run(adapter: SourceSeparator, exc_type: type[Exception] = exc_type) -> SeparationResult:
            calls.append(adapter.name)
            raise exc_type()

        with pytest.raises(exc_type):
            chain.run(run)
        assert calls == ["works"]  # no fallback to "broken"

"""Stage functions end-to-end on the DSP fallback chain (no ML extras required)."""

from __future__ import annotations

import pytest

from pianoforge.analysis.ir import StemInfo
from pianoforge.analysis.merge import merge_analysis
from pianoforge.analysis.registry import AdapterRegistry
from pianoforge.analysis.service import run_rhythm, run_separation, run_tonal, run_transcription
from pianoforge.config import Settings
from tests.synth import render_song


@pytest.fixture(scope="module")
def registry() -> AdapterRegistry:
    return AdapterRegistry(
        Settings(
            separator_chain=["hpss", "passthrough"],
            transcriber_chain=["pyin"],
            beat_tracker_chain=["librosa", "fixed"],
        )
    )


def test_fallback_pipeline_on_mix(registry: AdapterRegistry) -> None:
    song = render_song(bpm=100.0, repeats=3)
    progress: list[float] = []

    sep = run_separation(song.mix, registry, progress.append)
    assert sep.engine == "hpss@1"
    stems = sep.result.stems

    rhythm = run_rhythm(song.mix, stems, registry)
    assert rhythm.bpm == pytest.approx(100.0, rel=0.02)

    tonal = run_tonal(song.mix, stems, rhythm, registry)
    assert (tonal.key.tonic, tonal.key.mode) == (0, "major")
    labels = [c.label for c in tonal.chords if c.end - c.start > 1.0]
    assert {"C", "Am", "F", "G"} <= {lbl.split("/")[0].replace("7", "") for lbl in labels}

    transcription = run_transcription(song.mix, stems, registry)
    roles = {t.role: t for t in transcription.tracks}
    assert roles["melody"].engine == "pyin@1"
    assert len(roles["melody"].notes) > 10

    ir = merge_analysis(
        pipeline_version="test",
        duration=song.mix.duration,
        sample_rate=song.mix.sample_rate,
        separator_engine=sep.engine,
        stems=[
            StemInfo(kind=k, engine=sep.engine, rms_db=b.rms_db(), storage_key=k)
            for k, b in stems.items()
        ],
        rhythm=rhythm,
        tonal=tonal,
        transcription=transcription,
        extra_warnings=sep.result.warnings,
    )
    assert ir.engines["separator"] == "hpss@1"
    assert ir.tracks["harmony"].source == "chords"  # pyin is monophonic
    assert ir.sections and ir.sections[0].start == 0.0
    assert any("DSP fallback" in w for w in ir.warnings)
    assert progress and progress[-1] == pytest.approx(1.0)
    # Round-trips through JSON (what the worker stores in S3).
    assert type(ir).model_validate_json(ir.model_dump_json()) == ir

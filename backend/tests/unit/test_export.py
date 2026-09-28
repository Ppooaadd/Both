from __future__ import annotations

from pathlib import Path

import mido
import pytest
from music21 import converter

from pianoforge.arrangement.engine import arrange
from pianoforge.arrangement.params import ArrangementParams
from pianoforge.arrangement.score_ir import ScoreIR
from pianoforge.audio.buffer import read_audio
from pianoforge.export.engrave import VerovioEngraver
from pianoforge.export.midi import build_midi
from pianoforge.export.musicxml import write_musicxml
from pianoforge.export.render_audio import FluidSynthRenderer, SynthRenderer
from tests.synth import ground_truth_ir, render_song


@pytest.fixture(scope="module")
def score() -> ScoreIR:
    ir = ground_truth_ir(render_song(bpm=100.0, repeats=2))
    return arrange(ir, ArrangementParams(difficulty="intermediate"), "Export Test")


def test_midi_roundtrip(score: ScoreIR, tmp_path: Path) -> None:
    path = tmp_path / "s.mid"
    build_midi(score).save(str(path))
    mid = mido.MidiFile(str(path))
    assert mid.ticks_per_beat == score.tpq and len(mid.tracks) == 3
    metas = {m.type: m for m in mid.tracks[0] if m.is_meta}
    assert mido.tempo2bpm(metas["set_tempo"].tempo) == pytest.approx(score.tempo_bpm, abs=0.01)
    assert metas["key_signature"].key == "C"
    for track, hand in ((mid.tracks[1], "rh"), (mid.tracks[2], "lh")):
        ons = [m for m in track if m.type == "note_on" and m.velocity > 0]
        assert len(ons) == sum(1 for n in score.notes if n.hand == hand)
    pedal = [m for m in mid.tracks[2] if m.type == "control_change" and m.control == 64]
    assert len(pedal) == 4 * len(score.pedal)


def test_musicxml_structure(score: ScoreIR, tmp_path: Path) -> None:
    path = write_musicxml(score, tmp_path / "s.musicxml")
    parsed = converter.parse(str(path))
    parts = parsed.parts
    assert len(parts) == 2
    assert len(parts[0].getElementsByClass("Measure")) == score.measures
    assert parts[0].flatten().getElementsByClass("KeySignature")[0].sharps == 0
    xml = path.read_text()
    assert "<harmony" in xml and "<fingering" in xml
    assert "Andante (100 BPM)" in xml and 'tempo="100"' in xml


@pytest.mark.skipif(not VerovioEngraver.is_available(), reason="verovio/cairo not installed")
def test_pdf_engraving(score: ScoreIR, tmp_path: Path) -> None:
    xml = write_musicxml(score, tmp_path / "s.musicxml")
    pdf = VerovioEngraver().engrave(xml, tmp_path / "s.pdf")
    data = pdf.read_bytes()
    assert data.startswith(b"%PDF") and len(data) > 5000


@pytest.mark.parametrize("renderer", [SynthRenderer, FluidSynthRenderer])
def test_audio_render(score: ScoreIR, tmp_path: Path, renderer: type) -> None:
    if not renderer.is_available():
        pytest.skip(f"{renderer.name} not available")
    midi = tmp_path / "s.mid"
    build_midi(score).save(str(midi))
    wav = renderer().render(score, midi, tmp_path / "s.wav")
    buf = read_audio(wav)
    assert buf.sample_rate == 44_100
    assert score.duration_s - 0.5 <= buf.duration <= score.duration_s + 4.0
    assert buf.rms_db() > -40


@pytest.mark.skipif(not VerovioEngraver.is_available(), reason="verovio/cairo not installed")
def test_pdf_engraving_off_main_thread(score: ScoreIR, tmp_path: Path) -> None:
    """Regression: Verovio fonts are per-thread; Celery thread pools must still get a PDF."""
    import threading

    xml = write_musicxml(score, tmp_path / "s.musicxml")
    errors: list[BaseException] = []

    def run() -> None:
        try:
            VerovioEngraver().engrave(xml, tmp_path / "t.pdf")
        except BaseException as e:
            errors.append(e)

    t = threading.Thread(target=run)
    t.start()
    t.join()
    assert not errors, errors
    assert (tmp_path / "t.pdf").read_bytes().startswith(b"%PDF")

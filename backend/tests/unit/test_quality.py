"""Sung-melody segmentation, recording-driven dynamics and score engraving details."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from pianoforge.analysis.adapters.transcribe_crepe import segment_notes
from pianoforge.arrangement.dynamics import apply_dynamics, bar_levels
from pianoforge.arrangement.engine import arrange
from pianoforge.arrangement.events import Ev
from pianoforge.arrangement.params import ArrangementParams
from pianoforge.arrangement.score_ir import TPQ
from pianoforge.arrangement.timeline import Timeline
from pianoforge.db.enums import Difficulty
from pianoforge.export.engrave import CJK_FONT, _cjk_fonts
from pianoforge.export.musicxml import write_musicxml
from tests.synth import ground_truth_ir, render_song


def test_segmentation_splits_steps_and_reattacks_but_not_vibrato() -> None:
    t = np.arange(300)
    vibrato = 0.35 * np.sin(2 * np.pi * t / 18)  # +-35 cents
    midi = np.concatenate([np.full(100, 64.0), np.full(100, 67.0), np.full(100, 67.0)]) + vibrato
    voiced = np.ones(300, dtype=bool)
    voiced[95:100] = False  # breath between the first two notes
    reattack = np.zeros(300)
    reattack[200] = 3.0  # re-sung same pitch
    notes = segment_notes(midi, voiced, reattack)
    assert [p for *_, p in notes] == [64, 67, 67]
    assert notes[1][0] == 100 and notes[2][0] == 200


def test_segmentation_follows_a_pitch_step_without_a_gap() -> None:
    midi = np.concatenate([np.full(60, 60.0), np.full(60, 62.0)])
    notes = segment_notes(midi, np.ones(120, dtype=bool), np.zeros(120))
    assert [p for *_, p in notes] == [60, 62]
    assert abs(notes[1][0] - 60) <= 1


def _ir_with_loudness(profile: list[float]):  # type: ignore[no-untyped-def]
    ir = ground_truth_ir(render_song(bpm=100.0, repeats=2))
    n = len(ir.beats)
    per_part = n // len(profile) + 1
    loud = [v for v in profile for _ in range(per_part)][:n]
    return ir.model_copy(update={"beat_loudness_db": loud})


def test_dynamics_follow_the_recording_and_scale_velocities() -> None:
    ir = _ir_with_loudness([-14.0, -2.0])
    tl = Timeline(beats_per_bar=4, offset_beats=0.0, audio_beats=tuple(ir.beats))
    levels = bar_levels(ir, tl, measures=8, shift_beats=0)
    assert levels[0] in ("p", "mp") and levels[-1] == "f"
    events = [
        Ev("rh", 72, 0, TPQ, 80, "melody"),
        Ev("rh", 72, 7 * 4 * TPQ, 8 * 4 * TPQ, 80, "melody"),
    ]
    marks = apply_dynamics(events, levels, 4 * TPQ)
    assert events[0].vel < 80 < events[1].vel
    assert marks[0].mark == levels[0] and marks[-1].mark == "f"


def test_compressed_master_stays_at_one_level() -> None:
    ir = _ir_with_loudness([-2.0, -1.0, -2.5])
    tl = Timeline(beats_per_bar=4, offset_beats=0.0, audio_beats=tuple(ir.beats))
    assert set(bar_levels(ir, tl, measures=8, shift_beats=0)) == {"mf"}


def test_musicxml_has_tempo_above_dynamics_and_pedal(tmp_path: Path) -> None:
    ir = _ir_with_loudness([-14.0, -2.0])
    score = arrange(ir, ArrangementParams(difficulty=Difficulty.intermediate), "봄날")
    xml = write_musicxml(score, tmp_path / "a.musicxml").read_text(encoding="utf-8")
    assert '<direction placement="above">' in xml
    assert "<dynamics" in xml and "<f />" in xml.replace("<f/>", "<f />")
    assert "<pedal" in xml
    assert "봄날" in xml


def test_cjk_titles_switch_the_svg_text_font(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("pianoforge.export.engrave._cjk_font_installed", lambda: True)
    svg = '<text font-family="Times,serif">봄날의 멜로디</text>'
    assert CJK_FONT in _cjk_fonts(svg)
    latin = '<text font-family="Times,serif">Spring</text>'
    assert _cjk_fonts(latin) == latin

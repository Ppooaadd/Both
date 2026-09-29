"""Timing and note-fidelity logic: beat post-processing, meter, melody cleaning,
swing, tempo maps. Pure functions only (no ML models needed)."""

from __future__ import annotations

import io

import mido
import numpy as np
import pytest

from pianoforge.analysis.adapters.beats_beat_this import (
    bar_positions,
    choose_meter,
    pick_peaks,
    refine_peaks,
    repair_beats,
)
from pianoforge.analysis.ir import NoteEvent
from pianoforge.analysis.merge import fix_octaves, melody_line, merge_continuations
from pianoforge.analysis.service import annotate_attacks
from pianoforge.arrangement.engine import arrange, performance_beats
from pianoforge.arrangement.melody import build_melody
from pianoforge.arrangement.params import ArrangementParams
from pianoforge.arrangement.profiles import resolve_profile
from pianoforge.arrangement.score_ir import TPQ, swing_map
from pianoforge.arrangement.timeline import Timeline, detect_swing, unswing
from pianoforge.audio.buffer import AudioBuffer
from pianoforge.db.enums import Difficulty
from pianoforge.export.midi import build_midi
from tests.synth import ground_truth_ir, render_song


def _n(
    start: float, end: float, pitch: int, conf: float = 0.7, attack: float | None = None
) -> NoteEvent:
    return NoteEvent(start=start, end=end, pitch=pitch, velocity=90, confidence=conf, attack=attack)


# --------------------------------------------------------------------- beats
def test_pick_and_refine_peaks_sub_frame() -> None:
    x = np.zeros(100)
    x[40], x[41], x[39] = 1.0, 0.8, 0.2  # true peak between 40 and 41
    frames = pick_peaks(1 / (1 + np.exp(-10 * (x - 0.5))))
    assert list(frames) == [40]
    refined = refine_peaks(frames, x)
    assert 40.0 < refined[0] < 40.5


def test_repair_inserts_missing_and_drops_duplicate_beats() -> None:
    beats = np.arange(0, 10, 0.5)
    holed = np.delete(beats, [7, 8])  # a one-second hole
    doubled = np.sort(np.append(holed, 3.02))  # and a near-duplicate
    prob = np.ones(600) * 0.9
    fixed = repair_beats(doubled, prob)
    assert len(fixed) == len(beats)
    assert np.allclose(fixed, beats, atol=0.03)


@pytest.mark.parametrize("meter", [3, 4])
def test_choose_meter_and_phase_from_noisy_evidence(meter: int) -> None:
    rng = np.random.default_rng(meter)
    n = 60
    ev = np.where(np.arange(n) % meter == 1, 0.8, 0.2) + rng.normal(0, 0.1, n)
    got, pos = choose_meter(np.clip(ev, 0, 1))
    assert got == meter
    assert np.mean(pos[1::meter] == 0) > 0.9


def test_bar_positions_tolerate_one_irregular_bar() -> None:
    # 4/4 with one 2-beat bar in the middle; later downbeats must stay on the music.
    pattern = [1, 0, 0, 0] * 5 + [1, 0] + [1, 0, 0, 0] * 5
    ev = np.where(np.asarray(pattern) == 1, 0.9, 0.1)
    pos, _ = bar_positions(ev, 4)
    assert list(np.flatnonzero(pos == 0)) == list(np.flatnonzero(np.asarray(pattern) == 1))


# -------------------------------------------------------------------- melody
def test_merge_continuations_joins_splits_but_keeps_repeated_notes() -> None:
    notes = [
        _n(0.0, 0.40, 67, attack=1.5),
        _n(0.42, 0.70, 67, attack=0.2),  # vibrato split: same pitch, no attack
        _n(0.72, 0.80, 68, attack=0.1),  # short glide neighbour
        _n(1.00, 1.30, 64, attack=1.2),
        _n(1.32, 1.60, 64, attack=1.4),  # a real repeated note (attacked)
    ]
    out = merge_continuations(notes)
    assert [(round(n.start, 2), round(n.end, 2), n.pitch) for n in out] == [
        (0.0, 0.8, 67),
        (1.0, 1.3, 64),
        (1.32, 1.6, 64),
    ]


def test_fix_octaves_corrects_isolated_octave_up_errors() -> None:
    pitches = [67, 66, 78, 62, 74, 64, 66]  # 78 and 74 are octave-up errors
    notes = [_n(i * 0.5, i * 0.5 + 0.4, p) for i, p in enumerate(pitches)]
    assert [n.pitch for n in fix_octaves(notes)] == [67, 66, 66, 62, 62, 64, 66]


def test_melody_line_tail_has_no_attack() -> None:
    # A lower note that outlasts the top note keeps its audible tail, which is a
    # continuation, not a new attack.
    notes = [_n(0.0, 0.3, 76, attack=1.5), _n(0.1, 1.0, 64, attack=1.0)]
    line = melody_line(notes)
    tail = [n for n in line if n.pitch == 64]
    assert tail and tail[0].start == pytest.approx(0.3) and tail[0].attack == 0.0


def test_annotate_attacks_sees_onsets() -> None:
    sr = 22_050
    y = np.zeros(sr * 2, np.float32)
    t = np.arange(int(0.4 * sr)) / sr
    tone = (0.5 * np.sin(2 * np.pi * 440 * t) * np.exp(-t * 3)).astype(np.float32)
    y[sr // 2 : sr // 2 + tone.size] += tone
    buf = AudioBuffer.from_mono(y, sr)
    at, mid = annotate_attacks([_n(0.5, 0.8, 69), _n(0.75, 0.9, 69)], buf)
    assert at.attack is not None and mid.attack is not None
    assert at.attack > 0.8 > mid.attack


def test_quantisation_prefers_the_note_on_the_grid_point() -> None:
    tl = Timeline(beats_per_bar=4, offset_beats=0.0, audio_beats=tuple(np.arange(20) * 0.5))
    profile = resolve_profile(ArrangementParams(difficulty=Difficulty.beginner))
    on_beat = _n(1.0, 1.4, 64, conf=0.4).model_copy(update={"start_beat": 2.0, "end_beat": 2.8})
    louder_offbeat = _n(1.25, 2.0, 67, conf=1.0).model_copy(
        update={"start_beat": 2.5, "end_beat": 4.0, "velocity": 127}
    )
    events = build_melody([on_beat, louder_offbeat], tl, 0, profile, TPQ)
    assert events[0].start == 2 * TPQ and events[0].pitch == 64


# --------------------------------------------------------------------- swing
def test_swing_maps_are_inverse_and_detected() -> None:
    for f in (0.0, 0.25, 0.5, 0.8):
        assert unswing(swing_map(f, 0.66), 0.66) == pytest.approx(f)
    swung = [b + o for b in range(16) for o in (0.0, 0.66)]
    straight = [b + o for b in range(16) for o in (0.0, 0.5)]
    sixteenths = [b + o for b in range(16) for o in (0.0, 0.25, 0.5, 0.75)]
    assert detect_swing(swung) == pytest.approx(0.66, abs=0.01)
    assert detect_swing(straight) == 0.5
    assert detect_swing(sixteenths) == 0.5


def test_timeline_straightens_swung_offbeats() -> None:
    tl = Timeline(beats_per_bar=4, offset_beats=0.0, audio_beats=(0.0, 0.5), swing=2 / 3)
    assert tl.to_ticks(3 + 2 / 3) == pytest.approx(3.5 * TPQ)


# ---------------------------------------------------------------- tempo maps
def test_performance_beats_modes() -> None:
    src = [1.0, 1.5, 2.1, 2.6]
    assert performance_beats(src, 120.0, 1.0, "original") == [0.0, 0.5, 1.1, 1.6]
    assert performance_beats(src, 120.0, 0.5, "original") == [0.0, 1.0, 2.2, 3.2]
    assert performance_beats(src, 120.0, 1.0, "steady") == [0.0, 0.5, 1.0, 1.5]
    assert performance_beats([1.0, 0.9, 1.2], 60.0, 1.0, "original") == [0.0, 1.0, 2.0]


def _midi_note_times(mid: mido.MidiFile) -> list[float]:
    buf = io.BytesIO()
    mid.save(file=buf)
    buf.seek(0)
    t, out = 0.0, []
    for msg in mido.MidiFile(file=buf):
        t += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            out.append(round(t, 3))
    return sorted(out)


@pytest.mark.parametrize("timing", ["original", "steady"])
def test_rendered_timing_follows_the_recording(timing: str) -> None:
    song = render_song(bpm=100.0, repeats=2)
    ir = ground_truth_ir(song)
    # Stretch the second half: the recording speeds up to 120 BPM.
    beats = np.asarray(ir.beats)
    period = np.diff(beats)
    period[len(period) // 2 :] *= 100 / 120
    warped = np.concatenate([[beats[0]], beats[0] + np.cumsum(period)])
    ir = ir.model_copy(update={"beats": [float(b) for b in warped]})
    score = arrange(ir, ArrangementParams(difficulty=Difficulty.advanced, timing=timing), "t")  # type: ignore[arg-type]

    last = score.notes[-1]
    t_end = score.tick_to_seconds(last.start)
    bt = np.asarray(score.beat_times)
    expected = float(np.interp(last.start / TPQ, np.arange(bt.size), bt) - bt[0])
    if timing == "original":
        assert t_end == pytest.approx(expected, abs=0.02)
    else:
        assert t_end == pytest.approx(last.start / TPQ * 60 / score.tempo_bpm, abs=0.02)

    # The MIDI tempo map reproduces the same note times.
    midi_times = _midi_note_times(build_midi(score))
    score_times = sorted({round(score.tick_to_seconds(n.start), 3) for n in score.notes})
    assert np.allclose(sorted(set(midi_times)), score_times, atol=0.01)

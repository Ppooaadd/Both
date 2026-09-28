from __future__ import annotations

import itertools
from collections import defaultdict

import pytest

from pianoforge.analysis.ir import AnalysisIR, KeyInfo
from pianoforge.arrangement.engine import arrange
from pianoforge.arrangement.fingering import finger_line
from pianoforge.arrangement.harmony import Span
from pianoforge.arrangement.keys import easy_key_shift, key_fifths, target_key
from pianoforge.arrangement.params import ArrangementParams
from pianoforge.arrangement.patterns import LeftHand, PatternContext
from pianoforge.arrangement.profiles import BASE, resolve_profile
from pianoforge.arrangement.score_ir import TPQ, ScoreIR, ScoreNote
from pianoforge.arrangement.timeline import choose_grid
from pianoforge.arrangement.voicing import VoiceLeader
from pianoforge.db.enums import Difficulty
from tests.synth import TRIADS, ground_truth_ir, render_song

LEVELS = ("beginner", "intermediate", "advanced")


@pytest.fixture(scope="module")
def ir() -> AnalysisIR:
    return ground_truth_ir(render_song(bpm=100.0, repeats=2))


@pytest.fixture(scope="module")
def scores(ir: AnalysisIR) -> dict[str, ScoreIR]:
    return {d: arrange(ir, ArrangementParams(difficulty=d), "Test") for d in LEVELS}


def _chords_by_hand(score: ScoreIR) -> dict[str, dict[int, list[ScoreNote]]]:
    out: dict[str, dict[int, list[ScoreNote]]] = {"rh": defaultdict(list), "lh": defaultdict(list)}
    for n in score.notes:
        out[n.hand][n.start].append(n)
    return out


@pytest.mark.parametrize("level", LEVELS)
def test_playability_invariants(scores: dict[str, ScoreIR], level: str) -> None:
    score = scores[level]
    profile = BASE[Difficulty(level)]
    params = ArrangementParams(difficulty=level)
    hands = _chords_by_hand(score)
    for hand, chords in hands.items():
        starts = sorted(chords)
        for s in starts:
            group = chords[s]
            assert len(group) <= profile.max_poly, (hand, s)
            pitches = [n.pitch for n in group]
            assert max(pitches) - min(pitches) <= profile.max_span, (hand, s, pitches)
            assert len({n.dur for n in group}) == 1, "chord members share one duration"
            assert len(set(pitches)) == len(pitches), "no duplicate pitches"
        for a, b in itertools.pairwise(starts):
            assert chords[a][0].end <= b, f"{hand} chord stream overlaps at {a}"
    for n in score.notes:
        assert params.range_low <= n.pitch <= params.range_high
        assert n.end <= score.total_ticks
    # Hands never cross: LH stays below every RH note sounding at the same time.
    rh = [n for n in score.notes if n.hand == "rh"]
    for n in (n for n in score.notes if n.hand == "lh"):
        sounding = [r.pitch for r in rh if r.start < n.end and n.start < r.end]
        if sounding:
            assert n.pitch < min(sounding)


@pytest.mark.parametrize("level", LEVELS)
def test_melody_follows_source(scores: dict[str, ScoreIR], level: str) -> None:
    score = scores[level]
    song = render_song(bpm=100.0, repeats=2)
    melody = {n.start: n.pitch for n in score.notes if n.role == "melody"}
    # Ground-truth melody: one note per beat from bar 0 (no pickup in the synth song).
    hits = total = 0
    for i, (_s, _e, pitch) in enumerate(song.melody):
        total += 1
        got = melody.get(i * TPQ)
        hits += got is not None and got % 12 == pitch % 12
    assert hits / total >= 0.95
    assert all(n.start % score.grid == 0 for n in score.notes if n.role == "melody")


@pytest.mark.parametrize("level", LEVELS)
def test_left_hand_uses_chord_tones(scores: dict[str, ScoreIR], level: str) -> None:
    score = scores[level]
    song = render_song(bpm=100.0, repeats=2)
    bar = score.measure_ticks
    ok = total = 0
    for n in (n for n in score.notes if n.hand == "lh"):
        root, quality = song.chord_labels[n.start // bar][2:]
        tones = {(root + iv) % 12 for iv in TRIADS[quality]}
        total += 1
        ok += n.pitch % 12 in tones
    assert ok / total >= 0.98


def test_levels_differ_as_designed(scores: dict[str, ScoreIR]) -> None:
    b, i, a = (scores[d] for d in LEVELS)
    assert b.stats["difficulty_score"] < i.stats["difficulty_score"] < a.stats["difficulty_score"]
    assert b.stats["rh_max_poly"] == 1  # beginner: melody only
    assert int(a.stats["rh_max_poly"]) >= 2
    assert b.grid == TPQ and i.grid == TPQ // 2 and a.grid == TPQ // 4
    assert b.show_fingering and not a.show_fingering
    assert all(n.finger is not None for n in b.notes if n.hand == "rh")
    assert not b.pedal and a.pedal


def test_tempo_scale_and_transpose(ir: AnalysisIR) -> None:
    score = arrange(ir, ArrangementParams(tempo_scale=0.75, transpose=2), "T")
    assert score.tempo_bpm == pytest.approx(75.0)
    assert score.transpose == 2 and score.key.name == "D major" and score.key.fifths == 2
    base = arrange(ir, ArrangementParams(), "T")
    mel = [n.pitch % 12 for n in score.notes if n.role == "melody"]
    mel0 = [(n.pitch + 2) % 12 for n in base.notes if n.role == "melody"]
    assert mel == mel0


def test_easy_key_and_signatures() -> None:
    assert easy_key_shift(3, "major") == 2  # Eb -> F
    assert easy_key_shift(11, "minor") == -2  # Bm -> Am
    key, shift = target_key(KeyInfo(tonic=3, mode="major", confidence=1), 0, simplify=True)
    assert (key.name, key.fifths, shift) == ("F major", -1, 2)
    assert key_fifths(6, "major") == -6 and key_fifths(4, "minor") == 1


def test_crop_intro_outro(ir: AnalysisIR) -> None:
    shifted = ir.model_copy(
        update={
            "tracks": {
                **ir.tracks,
                "melody": ir.tracks["melody"].model_copy(
                    update={"notes": [n for n in ir.tracks["melody"].notes if n.start_beat >= 8]}
                ),
            }
        }
    )
    full = arrange(shifted, ArrangementParams(), "T")
    cropped = arrange(shifted, ArrangementParams(include_intro_outro=False), "T")
    assert cropped.measures == full.measures - 2
    assert min(n.start for n in cropped.notes if n.role == "melody") == 0
    assert len(cropped.beat_times) >= cropped.measures * 4


def test_alberti_pattern_shape() -> None:
    profile = resolve_profile(ArrangementParams(difficulty="intermediate"))
    ctx = PatternContext(
        profile=profile,
        beats_per_bar=4,
        grid=TPQ // 2,
        tempo_bpm=100,
        density=0.5,
        bass_at=lambda _t: None,
    )
    events = LeftHand(ctx).alberti(Span(0, 4 * TPQ, 0, "maj", None))
    names = [e.pitch % 12 for e in events[:4]]
    assert names == [0, 7, 4, 7]  # C G E G
    assert [e.start for e in events[:4]] == [0, 240, 480, 720]


def test_voice_leading_keeps_common_tones() -> None:
    vl = VoiceLeader(45, 62, 12)
    c = vl.next([0, 4, 7], 3)
    f = vl.next([5, 9, 0], 3)
    assert set(c) & set(f), f"C {c} -> F {f} should keep the common tone"
    assert sum(abs(x - y) for x, y in zip(c, f, strict=True)) <= 4


def test_fingering_scale() -> None:
    fingers = finger_line([60, 62, 64, 65, 67, 69, 71, 72])
    assert all(a != b for a, b in itertools.pairwise(fingers))
    crossings = sum(1 for a, b in itertools.pairwise(fingers) if b < a)
    assert crossings == 1  # one thumb-under in an octave
    assert fingers[-1] == 5


def test_triplet_grid_detection() -> None:
    triplets = [i * TPQ / 3 for i in range(48)]
    assert choose_grid(triplets, TPQ // 4, allow_triplets=True) == TPQ // 3
    straight = [i * TPQ / 4 for i in range(48)]
    assert choose_grid(straight, TPQ // 4, allow_triplets=True) == TPQ // 4
    assert choose_grid(triplets, TPQ // 2, allow_triplets=False) == TPQ // 2

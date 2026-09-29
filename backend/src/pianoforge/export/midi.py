"""Standard MIDI File (type 1) from ScoreIR: conductor track + one track per hand."""

from __future__ import annotations

from pathlib import Path

import mido

from pianoforge.arrangement.score_ir import ScoreIR

# (fifths, mode) -> mido key name
_MAJOR = {-7: "Cb", -6: "Gb", -5: "Db", -4: "Ab", -3: "Eb", -2: "Bb", -1: "F", 0: "C",
          1: "G", 2: "D", 3: "A", 4: "E", 5: "B", 6: "F#", 7: "C#"}  # fmt: skip
_MINOR = {-7: "Abm", -6: "Ebm", -5: "Bbm", -4: "Fm", -3: "Cm", -2: "Gm", -1: "Dm", 0: "Am",
          1: "Em", 2: "Bm", 3: "F#m", 4: "C#m", 5: "G#m", 6: "D#m", 7: "A#m"}  # fmt: skip

SUSTAIN_CC = 64


def key_name(fifths: int, mode: str) -> str:
    return (_MAJOR if mode == "major" else _MINOR)[fifths]


def _to_delta(abs_msgs: list[tuple[int, int, mido.Message | mido.MetaMessage]]) -> mido.MidiTrack:
    """Absolute-tick messages -> delta-time track. The middle tuple item orders ties
    (note-offs before note-ons at the same tick so repeated notes re-strike)."""
    track = mido.MidiTrack()
    last = 0
    for tick, _order, msg in sorted(abs_msgs, key=lambda x: (x[0], x[1])):
        track.append(msg.copy(time=tick - last))
        last = tick
    track.append(mido.MetaMessage("end_of_track", time=0))
    return track


def _played(score: ScoreIR, tick: int) -> int:
    """MIDI is the performance: swung off-beats sit at their played position."""
    return round(score.performed_tick(tick))


def tempo_map(score: ScoreIR) -> list[tuple[int, int, mido.MetaMessage]]:
    """``set_tempo`` events that reproduce ``performance_beats`` exactly.

    One event per beat whose length differs from the previous tempo by more
    than 0.2 % (below that the timing error stays under a millisecond per beat).
    """
    pb = score.performance_beats
    out: list[tuple[int, int, mido.MetaMessage]] = []
    last = mido.bpm2tempo(score.tempo_bpm)
    for k in range(len(pb) - 1):
        us = round((pb[k + 1] - pb[k]) * 1_000_000)
        if us <= 0:
            continue
        if k == 0 or abs(us - last) > 0.002 * last:
            out.append((k * score.tpq, 0, mido.MetaMessage("set_tempo", tempo=us)))
            last = us
    return out


def build_midi(score: ScoreIR) -> mido.MidiFile:
    mid = mido.MidiFile(type=1, ticks_per_beat=score.tpq)
    num, den = score.time_signature

    conductor: list[tuple[int, int, mido.Message | mido.MetaMessage]] = [
        (0, 0, mido.MetaMessage("track_name", name=score.title[:120])),
        (0, 0, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(score.tempo_bpm))),
        (0, 0, mido.MetaMessage("time_signature", numerator=num, denominator=den)),
        (0, 0, mido.MetaMessage("key_signature", key=key_name(score.key.fifths, score.key.mode))),
    ]
    conductor.extend(tempo_map(score))
    for sec in score.sections:
        conductor.append((sec.start, 1, mido.MetaMessage("marker", text=f"Section {sec.label}")))
    for ch in score.chords:
        conductor.append((ch.start, 1, mido.MetaMessage("text", text=ch.label)))
    mid.tracks.append(_to_delta(conductor))

    for channel, hand, name in ((0, "rh", "Piano Right Hand"), (1, "lh", "Piano Left Hand")):
        msgs: list[tuple[int, int, mido.Message | mido.MetaMessage]] = [
            (0, 0, mido.MetaMessage("track_name", name=name)),
            (0, 0, mido.Message("program_change", channel=channel, program=0)),
        ]
        for n in score.notes:
            if n.hand != hand:
                continue
            msgs.append(
                (
                    _played(score, n.start),
                    2,
                    mido.Message("note_on", channel=channel, note=n.pitch, velocity=n.velocity),
                )
            )
            msgs.append(
                (
                    _played(score, n.end),
                    1,
                    mido.Message("note_off", channel=channel, note=n.pitch, velocity=0),
                )
            )
        if hand == "lh":
            # Pedal lives on the left-hand track (channel 1) but is also sent on channel 0.
            for p in score.pedal:
                for chan in (0, 1):
                    msgs.append(
                        (
                            _played(score, p.start),
                            3,
                            mido.Message(
                                "control_change", channel=chan, control=SUSTAIN_CC, value=127
                            ),
                        )
                    )
                    msgs.append(
                        (
                            _played(score, p.end),
                            0,
                            mido.Message(
                                "control_change", channel=chan, control=SUSTAIN_CC, value=0
                            ),
                        )
                    )
        mid.tracks.append(_to_delta(msgs))
    return mid


def write_midi(score: ScoreIR, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    build_midi(score).save(str(path))
    return path

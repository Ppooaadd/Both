"""MusicXML (grand staff) from ScoreIR via music21.

Each hand is a chord stream, so each staff needs a single voice; music21 then
handles bar splitting, ties, tuplets and rests. Pitches are spelled with flats
in flat keys. Chord symbols and fingering (for levels that show it) are added.
"""

from __future__ import annotations

import re
from fractions import Fraction
from pathlib import Path

from music21 import (
    articulations,
    chord,
    clef,
    dynamics,
    expressions,
    harmony,
    key,
    layout,
    metadata,
    meter,
    note,
    pitch,
    stream,
    tempo,
)

from pianoforge.arrangement.score_ir import ScoreIR, ScoreNote

# music21 chord-symbol kinds per ScoreIR quality
_KIND = {"maj": "major", "min": "minor", "dim": "diminished", "aug": "augmented",
         "sus4": "suspended-fourth", "7": "dominant-seventh", "maj7": "major-seventh",
         "min7": "minor-seventh"}  # fmt: skip
_FLAT_NAMES = ("C", "D-", "D", "E-", "E", "F", "G-", "G", "A-", "A", "B-", "B")
_SHARP_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def _pitch(midi: int, flats: bool) -> pitch.Pitch:
    names = _FLAT_NAMES if flats else _SHARP_NAMES
    p = pitch.Pitch(names[midi % 12])
    p.octave = midi // 12 - 1
    # Cb/B# style edge cases do not occur with these tables; octave follows MIDI.
    return p


def tempo_word(bpm: float) -> str:
    for limit, word in ((60, "Largo"), (76, "Adagio"), (108, "Andante"), (120, "Moderato"),
                        (156, "Allegro"), (176, "Vivace")):  # fmt: skip
        if bpm < limit:
            return word
    return "Presto"


def _ql(ticks: int, tpq: int) -> Fraction:
    return Fraction(ticks, tpq)


def _staff(score: ScoreIR, hand: str, flats: bool, fingering: bool) -> stream.PartStaff:
    part = stream.PartStaff(id=f"P-{hand}")
    part.partName = "Piano"
    part.insert(0, clef.TrebleClef() if hand == "rh" else clef.BassClef())
    part.insert(0, key.KeySignature(score.key.fifths))
    num, den = score.time_signature
    part.insert(0, meter.TimeSignature(f"{num}/{den}"))
    if hand == "rh":
        # Text-only tempo (plus <sound tempo> for playback): the metronome note
        # glyph is a SMuFL private-use character that PDF conversion cannot draw.
        bpm = round(score.tempo_bpm)
        feel = " Swing" if score.swing >= 0.55 else ""
        mark = tempo.MetronomeMark(text=f"{tempo_word(bpm)}{feel} ({bpm} BPM)", number=bpm)
        mark.numberImplicit = True
        mark.placement = "above"  # type: ignore[assignment]  # music21 stub types it None
        part.insert(0, mark)

    groups: dict[int, list[ScoreNote]] = {}
    for n in score.notes:
        if n.hand == hand:
            groups.setdefault(n.start, []).append(n)
    for start in sorted(groups):
        members = sorted(groups[start], key=lambda n: n.pitch)
        ql = _ql(members[0].dur, score.tpq)
        if len(members) == 1:
            el: note.Note | chord.Chord = note.Note(
                _pitch(members[0].pitch, flats), quarterLength=ql
            )
            el.volume.velocity = members[0].velocity
        else:
            el = chord.Chord([_pitch(m.pitch, flats) for m in members], quarterLength=ql)
            el.volume.velocity = max(m.velocity for m in members)
        if fingering:
            for m in reversed(members):
                if m.finger is not None:
                    el.articulations.append(articulations.Fingering(m.finger))
        part.insert(_ql(start, score.tpq), el)

    if hand == "rh":
        # Dynamics sit between the staves (attached below the right hand).
        for dm in score.dynamics:
            d = dynamics.Dynamic(dm.mark)
            d.placement = "below"
            part.insert(_ql(dm.start, score.tpq), d)
    else:
        _pedal_marks(part, score)

    if hand == "rh":
        for ch in score.chords:
            try:
                sym = harmony.ChordSymbol(
                    root=_pitch(60 + ch.root, flats).name,
                    kind=_KIND.get(ch.quality, "major"),
                    bass=None if ch.bass is None else _pitch(60 + ch.bass, flats).name,
                )
                sym.writeAsChord = False
                part.insert(_ql(ch.start, score.tpq), sym)
            except Exception:  # noqa: S112 - an odd symbol must not fail the export
                continue

    # Pad to the full length so both staves have the same number of bars.
    end = _ql(score.total_ticks, score.tpq)
    last = part.highestTime
    if last < end:
        part.insert(last, note.Rest(quarterLength=end - last))
    return part


def _pedal_marks(part: stream.PartStaff, score: ScoreIR) -> None:
    """ "Ped. ... *" under the left hand for every sustain-pedal span."""
    notes = sorted(part.recurse().notes, key=lambda n: n.offset)
    for span in score.pedal:
        a, b = _ql(span.start, score.tpq), _ql(span.end, score.tpq)
        inside = [n for n in notes if a <= n.offset < b]
        if not inside:
            continue
        mark = expressions.PedalMark(inside)
        mark.pedalType = expressions.PedalType.Sustain
        mark.pedalForm = expressions.PedalForm.Symbol
        part.insert(0, mark)


TEMPO_DIRECTION = re.compile(r"<direction>(\s*<direction-type>\s*<words[^>]*>[^<]*BPM\))")


def build_musicxml_score(score: ScoreIR) -> stream.Score:
    flats = score.key.fifths < 0
    s = stream.Score()
    s.metadata = metadata.Metadata()
    s.metadata.title = score.title
    s.metadata.composer = f"Arr. PianoForge ({score.difficulty})"
    rh = _staff(score, "rh", flats, score.show_fingering)
    lh = _staff(score, "lh", flats, score.show_fingering)
    s.insert(0, rh)
    s.insert(0, lh)
    s.insert(0, layout.StaffGroup([rh, lh], name="Piano", abbreviation="Pno.", symbol="brace"))
    return s


def write_musicxml(score: ScoreIR, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = build_musicxml_score(score).makeNotation()
    out.write("musicxml", fp=str(path))
    # music21 drops the placement of text tempo marks; engravers then put the
    # tempo between the staves. It belongs above the top staff.
    xml = path.read_text(encoding="utf-8")
    xml = TEMPO_DIRECTION.sub(r'<direction placement="above">\1', xml, count=1)
    path.write_text(xml, encoding="utf-8")
    return path

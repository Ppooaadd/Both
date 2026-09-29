"""Synthetic benchmark songs with exact ground truth (no copyrighted material).

Unlike ``tests/synth.py`` these songs are built to stress the pipeline the way
real recordings do: human tempo drift and jitter, swing, 3/4, tempo changes,
drum-less ballads, pickups and intros, syncopated and 16th-note melodies, and a
vocal-like melody with vibrato. Every event is placed on a *musical* position
(beats) and mapped to time through the song's own beat clock, so the ground
truth is known both in seconds and in beats.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import numpy.typing as npt

from pianoforge.audio.buffer import AudioBuffer

SR = 44_100
F32 = npt.NDArray[np.float32]

MAJOR = (0, 2, 4, 5, 7, 9, 11)
MINOR = (0, 2, 3, 5, 7, 8, 10)
TRIAD = {"maj": (0, 4, 7), "min": (0, 3, 7)}

# Melody rhythms: (onset, duration) in beats, per bar.
RHYTHMS_4 = [
    [(0, 1), (1, 0.5), (1.5, 0.5), (2, 1.5), (3.5, 0.5)],
    [(0, 0.5), (0.5, 0.5), (1, 1), (2.5, 0.5), (3, 1)],
    [(0, 0.75), (0.75, 0.25), (1, 0.5), (1.5, 1), (2.5, 0.5), (3, 0.5), (3.5, 0.5)],
    [(0, 2), (2, 1), (3, 1)],
    [(0.5, 1), (1.5, 1), (2.5, 0.5), (3, 1)],
    [(0, 1.5), (1.5, 0.5), (2, 0.5), (2.5, 1.5)],
]
RHYTHMS_16 = [
    [(0, 0.25), (0.25, 0.25), (0.5, 0.5), (1, 0.25), (1.25, 0.25), (1.5, 0.5), (2, 1),
     (3, 0.5), (3.5, 0.5)],
    [(0, 0.5), (0.5, 0.25), (0.75, 0.75), (1.5, 0.5), (2, 0.25), (2.25, 0.25), (2.5, 1.5)],
]  # fmt: skip
RHYTHMS_3 = [
    [(0, 1), (1, 1), (2, 1)],
    [(0, 1.5), (1.5, 0.5), (2, 1)],
    [(0, 2), (2, 1)],
    [(0, 0.5), (0.5, 0.5), (1, 1), (2, 1)],
]


@dataclass(frozen=True)
class Spec:
    name: str
    bpm: float
    meter: int = 4
    bars: int = 16
    key: int = 0  # tonic pitch class
    mode: str = "major"
    progression: tuple[int, ...] = (0, 4, 5, 3)  # scale degrees (0-based) per bar
    drift: float = 0.0  # +- relative tempo modulation
    jitter_s: float = 0.0  # per-beat timing noise (s)
    swing: bool = False
    drums: bool = True
    accompaniment: str = "pad"  # pad | arpeggio | stabs
    sixteenths: bool = False
    intro_bars: int = 0  # chords only, no melody
    pickup_beats: float = 0.0  # melody notes before the first bar line
    tempo_change: tuple[int, float] | None = None  # (bar, new bpm)
    seed: int = 0
    lead: str = "voice"  # voice (formant singer) | synth (instrumental lead) | none


@dataclass
class Note:
    pos: float  # beats from bar 1, beat 1 (negative = pickup)
    dur: float  # beats
    pitch: int
    t0: float = 0.0
    t1: float = 0.0


@dataclass
class Song:
    spec: Spec
    mix: AudioBuffer
    beats: npt.NDArray[np.float64]  # beat times (s), first = bar 1 beat 1 (after pickup)
    downbeats: npt.NDArray[np.float64]
    melody: list[Note]
    chords: list[tuple[float, float, int, str]]  # t0, t1, root pc, quality
    stems: dict[str, AudioBuffer] = field(default_factory=dict)

    def pos_to_time(self, pos: float) -> float:
        return float(_pos_to_time(self.beats, pos, self.spec.swing))


def _pos_to_time(beats: npt.NDArray[np.float64], pos: float, swing: bool) -> float:
    k = int(np.floor(pos))
    frac = pos - k
    if swing and abs(frac - 0.5) < 1e-6:  # straight 8ths -> 2:1 triplet feel
        frac = 2 / 3
    k0 = min(max(k, 0), len(beats) - 2)
    period = beats[k0 + 1] - beats[k0]
    base = beats[0] + k * (beats[1] - beats[0]) if k < 0 else beats[min(k, len(beats) - 1)]
    if k >= len(beats) - 1:
        base = beats[-1] + (k - (len(beats) - 1)) * period
    return float(base + frac * period)


# ------------------------------------------------------------------ sound
def hz(p: float) -> float:
    return 440.0 * 2 ** ((p - 69) / 12)


def voice(pitch: int, dur: float, amp: float, vibrato: bool, rng: np.random.Generator) -> F32:
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    depth = 0.25 if vibrato else 0.0  # semitones
    rate = 5.5 + rng.uniform(-0.5, 0.5)
    onset_delay = np.clip((t - 0.15) / 0.2, 0, 1)
    f = hz(pitch) * 2 ** (depth * onset_delay * np.sin(2 * np.pi * rate * t) / 12)
    phase = 2 * np.pi * np.cumsum(f) / SR
    y = np.zeros(n)
    for h, a in ((1, 1.0), (2, 0.55), (3, 0.35), (4, 0.2), (5, 0.12), (6, 0.08)):
        y += a * np.sin(h * phase)
    env = np.minimum(1.0, t / 0.025) * np.exp(-t * 0.6)
    rel = min(int(0.04 * SR), n)
    env[n - rel :] *= np.linspace(1, 0, rel)
    return (amp * y * env).astype(np.float32)


# Vowel formants (Hz, bandwidth Hz) for a sung voice.
VOWELS = {
    "a": ((800, 80), (1150, 90), (2900, 120), (3900, 130)),
    "e": ((400, 60), (1900, 100), (2600, 120), (3300, 130)),
    "o": ((450, 70), (800, 80), (2830, 100), (3500, 130)),
    "u": ((350, 60), (600, 80), (2700, 100), (3400, 120)),
}


def sung(pitch: int, dur: float, amp: float, vowel: str, rng: np.random.Generator) -> F32:
    """Formant-synthesised sung vowel: glottal harmonics shaped by vowel resonances,
    delayed vibrato, pitch jitter, a breathy onset."""
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    rate = 5.3 + rng.uniform(-0.4, 0.4)
    vib = 0.35 * np.clip((t - 0.18) / 0.25, 0, 1) * np.sin(2 * np.pi * rate * t)
    drift = np.cumsum(rng.normal(0, 0.0008, n))  # slow pitch wander (semitones)
    scoop = -0.6 * np.exp(-t / 0.04)  # attack from slightly below
    f0 = hz(pitch) * 2 ** ((vib + drift + scoop) / 12)
    phase = 2 * np.pi * np.cumsum(f0) / SR
    y = np.zeros(n)
    formants = VOWELS[vowel]
    base = hz(pitch)
    for h in range(1, 40):
        fh = h * base
        if fh > 7000:
            break
        src = 1.0 / h**1.0  # glottal source roll-off (-6 dB/oct)
        gain = sum(1.0 / np.sqrt(1 + ((fh - fc) / (bw / 2)) ** 2) for fc, bw in formants)
        y += src * gain * np.sin(h * phase)
    breath = rng.standard_normal(n) * np.exp(-t / 0.05) * 0.15
    y = y / (np.max(np.abs(y)) + 1e-9) + breath
    env = np.minimum(1.0, t / 0.04) * (0.85 + 0.15 * np.exp(-t * 2))
    rel = min(int(0.06 * SR), n)
    env[n - rel :] *= np.linspace(1, 0, rel)
    return (amp * y * env).astype(np.float32)


def pluck(pitch: int, dur: float, amp: float) -> F32:
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    y = np.zeros(n)
    f = hz(pitch)
    for h in range(1, 8):
        if f * h < SR / 2:
            y += np.sin(2 * np.pi * f * h * t) * np.exp(-t * (1.5 + 0.8 * h)) / h
    env = np.minimum(1.0, t / 0.004)
    rel = min(int(0.03 * SR), n)
    env[n - rel :] *= np.linspace(1, 0, rel)
    return (amp * y * env).astype(np.float32)


def pad(pitch: int, dur: float, amp: float) -> F32:
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    f = hz(pitch)
    y = sum(np.sin(2 * np.pi * f * h * t + h) / h**1.5 for h in range(1, 5))
    env = np.minimum(1.0, t / 0.08)
    rel = min(int(0.1 * SR), n)
    env[n - rel :] *= np.linspace(1, 0, rel)
    return (amp * y * env).astype(np.float32)


def kick() -> F32:
    t = np.arange(int(0.3 * SR)) / SR
    f = 48 + 110 * np.exp(-t * 35)
    return (0.9 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 14)).astype(np.float32)


def noise(dur: float, decay: float, amp: float, rng: np.random.Generator, hp: bool) -> F32:
    n = int(dur * SR)
    y = rng.standard_normal(n)
    if hp:
        y = np.diff(y, prepend=0.0)
    t = np.arange(n) / SR
    return (amp * y * np.exp(-t * decay)).astype(np.float32)


# ------------------------------------------------------------------ build
def _beat_clock(spec: Spec, n_beats: int, rng: np.random.Generator) -> npt.NDArray[np.float64]:
    periods = []
    for i in range(n_beats + 8):
        bpm = spec.bpm
        if spec.tempo_change and i >= spec.tempo_change[0] * spec.meter:
            bpm = spec.tempo_change[1]
        bpm *= (
            1
            + spec.drift * np.sin(2 * np.pi * i / 29.0)
            + 0.5 * spec.drift * np.sin(2 * np.pi * i / 11.0 + 1.0)
        )
        periods.append(60.0 / bpm)
    t = np.concatenate([[0.0], np.cumsum(periods)])
    if spec.jitter_s:
        t = t + rng.normal(0, spec.jitter_s, t.shape)
        t = np.maximum.accumulate(t + np.arange(t.size) * 1e-4)
    return t


def build(spec: Spec) -> Song:
    rng = np.random.default_rng(spec.seed)
    scale = MAJOR if spec.mode == "major" else MINOR
    m = spec.meter
    total_bars = spec.intro_bars + spec.bars
    lead_s = 0.8 + rng.uniform(0, 0.4)
    clock = _beat_clock(spec, total_bars * m + 8, rng)
    pick = int(np.ceil(spec.pickup_beats))
    # clock[0] is `pick` beats before bar 1.
    beats_all = lead_s + clock
    bar1 = pick
    beats = beats_all[bar1 : bar1 + total_bars * m + 1]

    def time_at(pos: float) -> float:
        return _pos_to_time(beats_all, pos + bar1, spec.swing)

    duration = time_at(total_bars * m) + 1.5
    n = int(duration * SR)
    tracks = {k: np.zeros(n, np.float32) for k in ("vocals", "drums", "bass", "other")}

    def add(kind: str, sig: F32, t: float) -> None:
        i = round(t * SR)
        if i >= n:
            return
        j = min(n, i + len(sig))
        tracks[kind][i:j] += sig[: j - i]

    chords: list[tuple[float, float, int, str]] = []
    chord_tones_by_bar: list[tuple[int, str]] = []
    for bar in range(total_bars):
        deg = spec.progression[bar % len(spec.progression)]
        root = (spec.key + scale[deg]) % 12
        third = (scale[(deg + 2) % 7] - scale[deg]) % 12
        quality = "maj" if third == 4 else "min"
        chord_tones_by_bar.append((root, quality))
        p0, p1 = bar * m, (bar + 1) * m
        chords.append((time_at(p0), time_at(p1), root, quality))
        # accompaniment
        tones = [
            48 + (root + iv) % 12 + (12 if (root + iv) % 12 < 5 else 0) for iv in TRIAD[quality]
        ]
        if spec.accompaniment == "pad":
            for p in tones:
                add("other", pad(p, time_at(p1) - time_at(p0) - 0.02, 0.07), time_at(p0))
        elif spec.accompaniment == "arpeggio":
            seq = [tones[0], tones[1], tones[2], tones[1] + 12 if tones[1] < 60 else tones[1]]
            steps = int(m * 2)
            for s in range(steps):
                pos = p0 + s * 0.5
                add("other", pluck(seq[s % len(seq)], 0.9, 0.16), time_at(pos))
        else:  # stabs on every beat
            for b in range(m):
                for p in tones:
                    add("other", pluck(p, 0.35, 0.09), time_at(p0 + b))
        # bass
        bp = 36 + root
        hits = [0, 2] if m == 4 else [0]
        for b in hits:
            d = time_at(p0 + b + 1.8) - time_at(p0 + b)
            add("bass", pluck(bp, d, 0.4), time_at(p0 + b))
        # drums
        if spec.drums and bar >= (1 if spec.intro_bars else 0):
            for b in range(m):
                tb = time_at(p0 + b)
                if b == 0 or (m == 4 and b == 2):
                    add("drums", kick(), tb)
                elif m == 4 or b == 1:
                    add("drums", noise(0.18, 22, 0.3, rng, hp=False), tb)
                add("drums", noise(0.05, 90, 0.08, rng, hp=True), tb)
                add("drums", noise(0.05, 90, 0.06, rng, hp=True), time_at(p0 + b + 0.5))

    # melody
    melody: list[Note] = []
    rhythms = RHYTHMS_3 if m == 3 else (RHYTHMS_16 + RHYTHMS_4 if spec.sixteenths else RHYTHMS_4)
    pitch = 67 + spec.key % 12 if spec.key % 12 < 6 else 55 + spec.key % 12 + 12
    lo, hi = 62, 81

    def diatonic_step(p: int, step: int) -> int:
        pcs = sorted((spec.key + s) % 12 for s in scale)
        cand = [q for q in range(p - 5, p + 6) if q % 12 in pcs and q != p]
        cand.sort(key=lambda q: abs(q - p))
        up = [q for q in cand if q > p]
        down = [q for q in cand if q < p]
        seq = up if step > 0 else down
        return seq[min(abs(step) - 1, len(seq) - 1)] if seq else p

    if spec.pickup_beats:
        k = spec.pickup_beats
        pos = -k
        while pos < -1e-6:
            d = 0.5 if spec.pickup_beats <= 1 else 1.0
            melody.append(Note(spec.intro_bars * m + pos, d, pitch))
            pitch = diatonic_step(pitch, 1)
            pos += d
    for bar in range(spec.intro_bars, total_bars):
        root, quality = chord_tones_by_bar[bar]
        pattern = rhythms[int(rng.integers(len(rhythms)))]
        for onset, dur in pattern:
            if onset == 0:  # chord tone on the downbeat, nearest to the line
                tones = [q for q in range(lo, hi + 1) if (q - root) % 12 in TRIAD[quality]]
                pitch = min(tones, key=lambda q: abs(q - pitch))
            else:
                pitch = diatonic_step(pitch, int(rng.choice([-2, -1, -1, 1, 1, 2])))
                pitch = min(max(pitch, lo), hi)
            melody.append(Note(bar * m + onset, dur * 0.92, pitch))
    if spec.lead == "none":
        melody = []
    for note in melody:
        note.t0 = time_at(note.pos)
        note.t1 = time_at(note.pos + note.dur)
        if spec.lead == "voice":
            v = "aeou"[int(rng.integers(4))]
            add("vocals", sung(note.pitch, note.t1 - note.t0, 0.3, v, rng), note.t0)
        else:
            add("vocals", voice(note.pitch, note.t1 - note.t0, 0.22, True, rng), note.t0)

    stems = {k: AudioBuffer.from_mono(v, SR) for k, v in tracks.items()}
    mix = sum(tracks.values())
    mix = mix / max(1.0, float(np.max(np.abs(mix))) / 0.9)
    downbeats = beats[::m][: total_bars + 1]
    return Song(
        spec=spec,
        mix=AudioBuffer.from_mono(mix.astype(np.float32), SR),
        beats=beats,
        downbeats=downbeats,
        melody=melody,
        chords=chords,
        stems=stems,
    )


SPECS = [
    Spec("pop_drift", 100, drift=0.03, jitter_s=0.008, seed=1, key=2),
    Spec("ballad_nodrums", 72, drums=False, accompaniment="arpeggio", drift=0.05,
         jitter_s=0.012, pickup_beats=1.0, seed=2, key=7, bars=12),
    Spec("waltz", 138, meter=3, accompaniment="stabs", drift=0.02, seed=3, key=5,
         progression=(0, 3, 4, 0)),
    Spec("fast_minor", 164, mode="minor", progression=(0, 5, 2, 6), drift=0.01, seed=4, key=9,
         bars=20),
    Spec("swing", 118, swing=True, drift=0.02, jitter_s=0.006, seed=5, key=10),
    Spec("sixteenths", 92, sixteenths=True, drift=0.02, jitter_s=0.005, seed=6, key=4),
    Spec("intro_pickup", 108, intro_bars=4, pickup_beats=2.0, drift=0.02, seed=7, key=0),
    Spec("tempo_change", 90, tempo_change=(8, 120), jitter_s=0.005, seed=8, key=3),
    # Instrumental: the tune is a synth lead mixed into the accompaniment.
    Spec("inst_pop", 104, lead="synth", drift=0.02, jitter_s=0.006, seed=9, key=7),
    Spec("inst_waltz", 132, meter=3, lead="synth", accompaniment="stabs", seed=10, key=2,
         progression=(0, 3, 4, 0)),
]  # fmt: skip


# ------------------------------------------------------------ real vocals
VOCADITO = Path(__file__).resolve().parent / ".cache" / "vocadito"
KK_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])


def _key_of(pitches: list[int]) -> int:
    hist = np.bincount(np.asarray(pitches) % 12, minlength=12).astype(np.float64)
    return int(np.argmax([np.corrcoef(np.roll(KK_MAJOR, k), hist)[0, 1] for k in range(12)]))


def real_vocal_song(track: int, bpm: float = 96.0) -> Song:
    """A vocadito solo singing track (CC BY 4.0) over a synthetic band in its key.

    The singer is not aligned to the band's beat, so only melody-oriented
    metrics are meaningful for these songs.
    """
    import soundfile as sf

    audio, sr = sf.read(str(VOCADITO / "Audio" / f"vocadito_{track}.wav"), dtype="float32")
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    notes_csv = np.loadtxt(
        VOCADITO / "Annotations" / "Notes" / f"vocadito_{track}_notesA1.csv", delimiter=",", ndmin=2
    )
    pitches = [round(69 + 12 * np.log2(f / 440.0)) for f in notes_csv[:, 1]]
    key = _key_of(pitches)
    dur = len(audio) / sr
    bars = int(np.ceil((dur - 0.5) / (4 * 60.0 / bpm))) + 1
    band = build(
        Spec(
            f"vocadito_{track}",
            bpm,
            bars=bars,
            key=key,
            lead="none",
            seed=100 + track,
            progression=(0, 5, 3, 4),
        )
    )
    n = len(band.mix.mono_at(SR))
    voc = np.zeros(n, np.float32)
    v = (
        audio
        if sr == SR
        else np.interp(np.arange(int(dur * SR)) / SR, np.arange(len(audio)) / sr, audio).astype(
            np.float32
        )
    )
    voc[: min(n, len(v))] = v[: min(n, len(v))]
    voc *= 0.5 / (np.sqrt(np.mean(voc**2)) * 4 + 1e-9)
    band_tracks = {k: b.mono_at(SR)[:n] for k, b in band.stems.items()}
    band_tracks["vocals"] = voc
    mix = sum(band_tracks.values())
    mix = mix / max(1.0, float(np.max(np.abs(mix))) / 0.9)

    def pos_of(t: float) -> float:
        return float(np.interp(t, band.beats, np.arange(len(band.beats))))

    melody = [
        Note(
            pos=pos_of(on), dur=pos_of(on + d) - pos_of(on), pitch=p, t0=float(on), t1=float(on + d)
        )
        for (on, _f, d), p in zip(notes_csv, pitches, strict=True)
    ]
    spec = Spec(f"vocadito_{track}", bpm, bars=bars, key=key, lead="real")
    return Song(
        spec=spec,
        mix=AudioBuffer.from_mono(mix.astype(np.float32), SR),
        beats=band.beats,
        downbeats=band.downbeats,
        melody=melody,
        chords=band.chords,
        stems={k: AudioBuffer.from_mono(v2, SR) for k, v2 in band_tracks.items()},
    )


REAL_VOCAL_TRACKS = (1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34)

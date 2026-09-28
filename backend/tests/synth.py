"""Deterministic synthetic music for tests (no copyrighted material).

``render_song`` produces a mix plus ground-truth stems for a I-vi-IV-V
progression with melody, bass and a kick/snare/hat pattern.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from pianoforge.audio.buffer import AudioBuffer

SR = 22_050
F32 = npt.NDArray[np.float32]

# (root pitch class, quality) per bar; C major: C Am F G
PROGRESSION = [(0, "maj"), (9, "min"), (5, "maj"), (7, "maj")]
TRIADS = {"maj": (0, 4, 7), "min": (0, 3, 7)}
# Melody: MIDI pitch per beat (one bar = 4 beats) matching the progression.
MELODY = [
    [72, 76, 79, 76],
    [72, 69, 72, 76],
    [77, 76, 72, 69],
    [71, 74, 79, 74],
]


def midi_hz(p: float) -> float:
    return 440.0 * 2 ** ((p - 69) / 12)


def tone(pitch: float, dur: float, amp: float, harmonics: int = 6) -> F32:
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = midi_hz(pitch)
    y = np.zeros(n)
    for h in range(1, harmonics + 1):
        if f * h < SR / 2:
            y += np.sin(2 * np.pi * f * h * t) / h**1.3
    attack = min(int(0.01 * SR), n)
    env = np.exp(-t * 2.5)
    env[:attack] *= np.linspace(0, 1, attack)
    release = min(int(0.03 * SR), n)
    env[n - release :] *= np.linspace(1, 0, release)
    return (amp * y * env).astype(np.float32)


def kick(dur: float = 0.25) -> F32:
    n = int(dur * SR)
    t = np.arange(n) / SR
    freq = 50 + 100 * np.exp(-t * 30)
    return (0.9 * np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 18)).astype(np.float32)


def noise_hit(dur: float, decay: float, amp: float, seed: int) -> F32:
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    t = np.arange(n) / SR
    return (amp * rng.standard_normal(n) * np.exp(-t * decay)).astype(np.float32)


@dataclass
class Song:
    mix: AudioBuffer
    stems: dict[str, AudioBuffer]
    bpm: float
    beats: F32
    chord_labels: list[tuple[float, float, int, str]]  # start, end, root, quality
    melody: list[tuple[float, float, int]]


def render_song(bpm: float = 100.0, repeats: int = 4, offset: float = 0.5) -> Song:
    beat = 60.0 / bpm
    bars = len(PROGRESSION) * repeats
    total = offset + bars * 4 * beat + 1.0
    n = int(total * SR)
    vocals = np.zeros(n, np.float32)
    drums = np.zeros(n, np.float32)
    bass = np.zeros(n, np.float32)
    other = np.zeros(n, np.float32)

    def add(buf: F32, sig: F32, t: float) -> None:
        i = int(t * SR)
        j = min(n, i + len(sig))
        buf[i:j] += sig[: j - i]

    chord_labels = []
    melody = []
    for bar in range(bars):
        root, quality = PROGRESSION[bar % len(PROGRESSION)]
        t0 = offset + bar * 4 * beat
        chord_labels.append((t0, t0 + 4 * beat, root, quality))
        for iv in TRIADS[quality]:
            for b in range(4):
                add(other, tone(60 + (root + iv) % 12, beat * 0.95, 0.12), t0 + b * beat)
        bass_pitch = 36 + root
        add(bass, tone(bass_pitch, beat * 1.9, 0.35, harmonics=3), t0)
        add(bass, tone(bass_pitch, beat * 1.9, 0.3, harmonics=3), t0 + 2 * beat)
        for b, p in enumerate(MELODY[bar % len(MELODY)]):
            add(vocals, tone(p, beat * 0.9, 0.25, harmonics=4), t0 + b * beat)
            melody.append((t0 + b * beat, t0 + b * beat + beat * 0.9, p))
        for b in range(4):
            tb = t0 + b * beat
            if b in (0, 2):
                add(drums, kick(), tb)
            else:
                add(drums, noise_hit(0.15, 25, 0.35, seed=bar * 4 + b), tb)
            add(drums, noise_hit(0.05, 80, 0.12, seed=1000 + bar * 8 + b), tb + beat / 2)

    stems = {
        k: AudioBuffer.from_mono(v, SR)
        for k, v in {"vocals": vocals, "drums": drums, "bass": bass, "other": other}.items()
    }
    mix = vocals + drums + bass + other
    mix = mix / max(1.0, float(np.max(np.abs(mix))) / 0.9)
    beats = (offset + np.arange(bars * 4) * beat).astype(np.float32)
    return Song(
        mix=AudioBuffer.from_mono(mix, SR),
        stems=stems,
        bpm=bpm,
        beats=beats,
        chord_labels=chord_labels,
        melody=melody,
    )

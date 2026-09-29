"""Piano audio rendering adapters: ScoreIR/MIDI -> WAV.

* ``fluidsynth`` FluidSynth CLI with a General MIDI / piano SoundFont (best quality)
* ``synth``      numpy additive piano model (inharmonic partials, per-partial
                 decay, damper release, sustain pedal). No system dependencies.
"""

from __future__ import annotations

import shutil
import subprocess
from abc import abstractmethod
from functools import lru_cache
from pathlib import Path
from typing import ClassVar

import numpy as np
import numpy.typing as npt

from pianoforge.analysis.interfaces import Adapter
from pianoforge.arrangement.score_ir import ScoreIR
from pianoforge.audio.buffer import AudioBuffer, read_audio, write_wav
from pianoforge.audio.normalize import normalize_loudness
from pianoforge.config import get_settings

SR = 44_100
TAIL_S = 2.0
TARGET_LUFS = -16.0

SOUNDFONT_SEARCH = (
    "/usr/share/sounds/sf2/SalamanderGrandPiano.sf2",
    "/usr/share/sounds/sf2/FluidR3_GM.sf2",
    "/usr/share/sounds/sf2/default-GM.sf2",
    "/usr/share/soundfonts/FluidR3_GM.sf2",
    "/usr/share/soundfonts/default.sf2",
)


class AudioRenderer(Adapter):
    role: ClassVar[str] = "renderer"

    @abstractmethod
    def render(self, score: ScoreIR, midi: Path, wav: Path) -> Path: ...


def _finish(buf: AudioBuffer, wav: Path) -> Path:
    normalized, _ = normalize_loudness(buf, TARGET_LUFS)
    return write_wav(normalized, wav, subtype="PCM_16")


def find_soundfont() -> str | None:
    configured = get_settings().soundfont_path
    if configured and Path(configured).is_file():
        return configured
    return next((p for p in SOUNDFONT_SEARCH if Path(p).is_file()), None)


class FluidSynthRenderer(AudioRenderer):
    name: ClassVar[str] = "fluidsynth"
    version: ClassVar[str] = "cli"

    @classmethod
    def is_available(cls) -> bool:
        return shutil.which("fluidsynth") is not None and find_soundfont() is not None

    def render(self, score: ScoreIR, midi: Path, wav: Path) -> Path:
        sf2 = find_soundfont()
        assert sf2 is not None
        raw = wav.with_suffix(".raw.wav")
        cmd = [
            "fluidsynth",
            "-ni",
            "-q",
            "-g",
            "0.7",
            "-r",
            str(SR),
            "-F",
            str(raw),
            sf2,
            str(midi),
        ]
        timeout = max(60.0, score.duration_s * 2)
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)  # noqa: S603
        if proc.returncode != 0 or not raw.exists():
            raise RuntimeError(f"fluidsynth failed: {proc.stderr.decode(errors='replace')[-300:]}")
        buf = read_audio(raw)
        raw.unlink(missing_ok=True)
        if buf.frames == 0 or float(np.max(np.abs(buf.samples))) < 1e-5:
            raise RuntimeError("fluidsynth rendered silence")
        return _finish(buf, wav)


# ------------------------------------------------------------------ numpy piano
TONE_S = 6.0
RELEASE_S = 0.12
N_PARTIALS = 10
INHARMONICITY = 0.0004


@lru_cache(maxsize=128)
def piano_tone(pitch: int, sr: int = SR) -> npt.NDArray[np.float32]:
    """One struck string, TONE_S long, peak-normalised."""
    f0 = 440.0 * 2 ** ((pitch - 69) / 12)
    t = np.arange(int(TONE_S * sr)) / sr
    tau0 = float(np.clip(3.5 * (261.6 / f0) ** 0.6, 0.35, 8.0))
    y = np.zeros_like(t)
    for k in range(1, N_PARTIALS + 1):
        fk = k * f0 * np.sqrt(1 + INHARMONICITY * k * k)
        if fk >= sr / 2:
            break
        amp = (1.0 / k**1.1) * np.exp(-0.12 * k)
        tau = tau0 / (1 + 0.45 * (k - 1))
        y += amp * np.sin(2 * np.pi * fk * t) * np.exp(-t / tau)
    attack = int(0.003 * sr)
    y[:attack] *= np.linspace(0.0, 1.0, attack)
    peak = float(np.max(np.abs(y))) or 1.0
    return (y / peak).astype(np.float32)


class SynthRenderer(AudioRenderer):
    name: ClassVar[str] = "synth"
    version: ClassVar[str] = "1"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def render(self, score: ScoreIR, midi: Path, wav: Path) -> Path:
        total = int((score.duration_s + TAIL_S) * SR)
        out = np.zeros(total, dtype=np.float32)
        pedals = sorted((p.start, p.end) for p in score.pedal)
        release = int(RELEASE_S * SR)
        for n in score.notes:
            end_tick = n.end
            for ps, pe in pedals:  # dampers stay up while the pedal is down
                if ps <= end_tick < pe:
                    end_tick = pe
                    break
            t0 = score.tick_to_seconds(n.start)
            s = int(t0 * SR)
            hold = int((score.tick_to_seconds(end_tick) - t0) * SR)
            tone = piano_tone(n.pitch)
            length = min(hold + release, len(tone), total - s)
            if length <= 0:
                continue
            seg = tone[:length].copy()
            if hold < length:
                seg[hold:] *= np.linspace(1.0, 0.0, length - hold, dtype=np.float32)
            out[s : s + length] += seg * np.float32(0.25 * (n.velocity / 127.0) ** 1.6)
        return _finish(AudioBuffer.from_mono(out, SR), wav)


RENDERERS: list[type[AudioRenderer]] = [FluidSynthRenderer, SynthRenderer]

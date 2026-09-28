"""In-memory audio representation and file I/O helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np
import numpy.typing as npt
import soundfile as sf

FloatArray = npt.NDArray[np.float32]


@dataclass(frozen=True)
class AudioBuffer:
    """Planar float32 audio: ``samples.shape == (channels, frames)``, range [-1, 1]."""

    samples: FloatArray
    sample_rate: int

    def __post_init__(self) -> None:
        if self.samples.ndim != 2:
            raise ValueError("samples must be 2-D (channels, frames)")
        if self.samples.dtype != np.float32:
            object.__setattr__(self, "samples", self.samples.astype(np.float32))

    @property
    def channels(self) -> int:
        return int(self.samples.shape[0])

    @property
    def frames(self) -> int:
        return int(self.samples.shape[1])

    @property
    def duration(self) -> float:
        return self.frames / float(self.sample_rate)

    def mono(self) -> FloatArray:
        return np.asarray(self.samples.mean(axis=0), dtype=np.float32)

    def resampled(self, sr: int) -> AudioBuffer:
        if sr == self.sample_rate:
            return self
        y = librosa.resample(
            self.samples, orig_sr=self.sample_rate, target_sr=sr, res_type="soxr_hq"
        )
        return AudioBuffer(np.asarray(y, dtype=np.float32), sr)

    def mono_at(self, sr: int) -> FloatArray:
        """Mono signal at ``sr``; the common input for analysis adapters."""
        y = self.mono()
        if sr != self.sample_rate:
            y = librosa.resample(y, orig_sr=self.sample_rate, target_sr=sr, res_type="soxr_hq")
        return np.asarray(y, dtype=np.float32)

    def rms_db(self) -> float:
        rms = float(np.sqrt(np.mean(np.square(self.samples, dtype=np.float64))))
        return 20.0 * float(np.log10(max(rms, 1e-10)))

    @classmethod
    def from_mono(cls, y: npt.NDArray[np.floating], sr: int) -> AudioBuffer:
        return cls(np.asarray(y, dtype=np.float32)[np.newaxis, :], sr)


def read_audio(path: Path) -> AudioBuffer:
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return AudioBuffer(np.ascontiguousarray(data.T), int(sr))


def write_flac(buf: AudioBuffer, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(buf.samples, -1.0, 1.0)
    sf.write(str(path), clipped.T, buf.sample_rate, format="FLAC", subtype="PCM_24")
    return path


def write_wav(buf: AudioBuffer, path: Path, subtype: str = "PCM_16") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(buf.samples, -1.0, 1.0)
    sf.write(str(path), clipped.T, buf.sample_rate, format="WAV", subtype=subtype)
    return path


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()

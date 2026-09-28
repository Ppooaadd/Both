"""DSP fallback separation: HPSS + REPET-SIM vocal extraction + low-pass bass.

Quality is well below Demucs but it needs only librosa/scipy and runs on any CPU.

* drums  = percussive component of HPSS
* vocals = non-repeating foreground of the harmonic component (REPET-SIM,
           computed in ~30 s windows to bound the O(n^2) similarity search)
* bass   = harmonic background below ~200 Hz
* other  = remaining harmonic background
"""

from __future__ import annotations

from typing import ClassVar

import librosa
import numpy as np
import numpy.typing as npt

from pianoforge.analysis.interfaces import ProgressFn, SeparationResult, SourceSeparator, _noop
from pianoforge.audio.buffer import AudioBuffer

SR = 22_050
N_FFT = 2048
HOP = 512
WINDOW_S = 30.0
BASS_CUTOFF_HZ = 200.0


def _repet_sim_mask(mag: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    """Soft mask of the foreground (vocals) for one window of a magnitude spectrogram."""
    frames = mag.shape[1]
    if frames < 16:
        return np.zeros_like(mag)
    width = int(min(librosa.time_to_frames(2.0, sr=SR, hop_length=HOP), frames // 2))
    bg = librosa.decompose.nn_filter(mag, aggregate=np.median, metric="cosine", width=max(width, 1))
    bg = np.minimum(mag, bg)
    margin_v = 10.0
    power = 2.0
    mask = librosa.util.softmask(mag - bg, margin_v * bg, power=power)
    return np.asarray(mask, dtype=np.float32)


class HpssSeparator(SourceSeparator):
    name: ClassVar[str] = "hpss"
    version: ClassVar[str] = "1"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def separate(self, audio: AudioBuffer, progress: ProgressFn = _noop) -> SeparationResult:
        y = audio.mono_at(SR)
        stft = librosa.stft(y, n_fft=N_FFT, hop_length=HOP)
        progress(0.1)
        harm, perc = librosa.decompose.hpss(stft, margin=(1.0, 2.0))
        progress(0.3)

        mag = np.abs(harm).astype(np.float32)
        vocal_mask = np.zeros_like(mag)
        win = int(librosa.time_to_frames(WINDOW_S, sr=SR, hop_length=HOP))
        n = mag.shape[1]
        starts = list(range(0, n, win))
        for i, s in enumerate(starts):
            e = min(s + win, n)
            vocal_mask[:, s:e] = _repet_sim_mask(mag[:, s:e])
            progress(0.3 + 0.6 * (i + 1) / len(starts))

        # Vocals live roughly in 100 Hz..8 kHz; suppress mask elsewhere.
        freqs = librosa.fft_frequencies(sr=SR, n_fft=N_FFT)
        band = ((freqs >= 100) & (freqs <= 8000)).astype(np.float32)[:, None]
        vocal_mask *= band

        vocals_spec = harm * vocal_mask
        background = harm * (1.0 - vocal_mask)
        low = (freqs < BASS_CUTOFF_HZ).astype(np.float32)[:, None]
        bass_spec = background * low
        other_spec = background * (1.0 - low)

        def inv(spec: npt.NDArray[np.complex64]) -> AudioBuffer:
            sig = librosa.istft(spec, hop_length=HOP, length=len(y))
            return AudioBuffer.from_mono(sig, SR)

        stems = {
            "vocals": inv(vocals_spec),
            "drums": inv(perc),
            "bass": inv(bass_spec),
            "other": inv(other_spec),
        }
        progress(1.0)
        return SeparationResult(
            stems=stems,
            engine=self.engine_id,
            warnings=["separator: DSP fallback in use; stems are approximate"],
        )

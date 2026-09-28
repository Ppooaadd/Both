"""Demucs (Hybrid Transformer) source separation. Requires the ``ml`` extra."""

from __future__ import annotations

import importlib.util
import threading
from typing import Any, ClassVar

import numpy as np

from pianoforge.analysis.interfaces import ProgressFn, SeparationResult, SourceSeparator, _noop
from pianoforge.audio.buffer import AudioBuffer
from pianoforge.config import get_settings

_MODEL_LOCK = threading.Lock()


class DemucsSeparator(SourceSeparator):
    name: ClassVar[str] = "demucs"
    version: ClassVar[str] = "4"

    def __init__(self) -> None:
        self._model: Any = None
        self._device: str = "cpu"

    @classmethod
    def is_available(cls) -> bool:
        return all(importlib.util.find_spec(m) is not None for m in ("torch", "demucs"))

    def _load(self) -> Any:
        with _MODEL_LOCK:
            if self._model is None:
                import torch
                from demucs.pretrained import get_model

                settings = get_settings()
                model = get_model(settings.demucs_model)
                model.eval()
                device = settings.demucs_device
                if device == "auto":
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                self._device = device
                self._model = model
        return self._model

    def separate(self, audio: AudioBuffer, progress: ProgressFn = _noop) -> SeparationResult:
        import torch
        from demucs.apply import apply_model

        model = self._load()
        progress(0.05)
        src = audio.resampled(int(model.samplerate))
        wav = src.samples
        if wav.shape[0] == 1 and model.audio_channels == 2:
            wav = np.repeat(wav, 2, axis=0)
        elif wav.shape[0] > model.audio_channels:
            wav = wav[: model.audio_channels]

        tensor = torch.from_numpy(np.ascontiguousarray(wav))
        ref = tensor.mean(0)
        mean, std = ref.mean(), ref.std().clamp_min(1e-8)
        tensor = (tensor - mean) / std

        with torch.inference_mode():
            out = apply_model(
                model,
                tensor[None],
                device=self._device,
                shifts=1,
                split=True,
                overlap=0.25,
                progress=False,
                num_workers=0,
            )[0]
        out = out * std + mean
        progress(0.95)

        stems: dict[str, AudioBuffer] = {}
        for name, source in zip(model.sources, out, strict=True):
            if name in ("vocals", "drums", "bass", "other"):
                stems[name] = AudioBuffer(source.cpu().numpy().astype(np.float32), src.sample_rate)
        progress(1.0)
        return SeparationResult(stems=stems, engine=self.engine_id)

"""Spotify Basic Pitch polyphonic transcription. Requires the ``ml`` extra."""

from __future__ import annotations

import importlib.util
import tempfile
import threading
from pathlib import Path
from typing import Any, ClassVar

from pianoforge.analysis.interfaces import NoteTranscriber, ProgressFn, TranscriptionRequest, _noop
from pianoforge.analysis.ir import NoteEvent
from pianoforge.audio.buffer import write_wav

_LOCK = threading.Lock()

# Per-role thresholds. Melody favours precision; harmony favours recall.
_ROLE_PARAMS: dict[str, dict[str, float | bool]] = {
    "melody": {"onset_threshold": 0.55, "frame_threshold": 0.35, "min_ms": 80.0, "melodia": True},
    "bass": {"onset_threshold": 0.5, "frame_threshold": 0.3, "min_ms": 100.0, "melodia": True},
    "harmony": {
        "onset_threshold": 0.45,
        "frame_threshold": 0.25,
        "min_ms": 100.0,
        "melodia": False,
    },
}


class BasicPitchTranscriber(NoteTranscriber):
    name: ClassVar[str] = "basic_pitch"
    version: ClassVar[str] = "0.4"
    polyphonic: ClassVar[bool] = True

    def __init__(self) -> None:
        self._model: Any = None

    @classmethod
    def is_available(cls) -> bool:
        return importlib.util.find_spec("basic_pitch") is not None

    def _load(self) -> Any:
        with _LOCK:
            if self._model is None:
                from basic_pitch import ICASSP_2022_MODEL_PATH
                from basic_pitch.inference import Model

                self._model = Model(ICASSP_2022_MODEL_PATH)
        return self._model

    def transcribe(
        self, request: TranscriptionRequest, progress: ProgressFn = _noop
    ) -> list[NoteEvent]:
        from basic_pitch.inference import predict

        model = self._load()
        params = _ROLE_PARAMS[request.role]
        progress(0.05)
        with tempfile.TemporaryDirectory(prefix="pf-bp-") as tmp:
            wav = write_wav(request.audio.resampled(22_050), Path(tmp) / "in.wav")
            _, _, events = predict(
                str(wav),
                model,
                onset_threshold=float(params["onset_threshold"]),
                frame_threshold=float(params["frame_threshold"]),
                minimum_note_length=float(params["min_ms"]),
                minimum_frequency=request.min_hz,
                maximum_frequency=request.max_hz,
                multiple_pitch_bends=False,
                melodia_trick=bool(params["melodia"]),
            )
        progress(0.95)

        notes: list[NoteEvent] = []
        for start, end, pitch, amplitude, _bends in events:
            if end <= start:
                continue
            amp = float(max(0.0, min(1.0, amplitude)))
            notes.append(
                NoteEvent(
                    start=float(start),
                    end=float(end),
                    pitch=int(pitch),
                    velocity=round(30 + amp * 97),
                    confidence=amp,
                )
            )
        notes.sort(key=lambda n: (n.start, n.pitch))
        progress(1.0)
        return notes

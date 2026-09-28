"""Monophonic fallback transcription with probabilistic YIN.

Produces one note line per role. For ``harmony`` (inherently polyphonic) it
returns no notes; the merge step then derives harmony from recognised chords.
"""

from __future__ import annotations

from typing import ClassVar

import librosa
import numpy as np
import numpy.typing as npt
import scipy.ndimage

from pianoforge.analysis.interfaces import NoteTranscriber, ProgressFn, TranscriptionRequest, _noop
from pianoforge.analysis.ir import NoteEvent

SR = 22_050
HOP = 256
FRAME = 2048
MIN_NOTE_S = 0.08
VOICED_PROB = 0.35


def _segments(
    midi: npt.NDArray[np.float64], voiced: npt.NDArray[np.bool_], onset_frames: set[int]
) -> list[tuple[int, int, int]]:
    """Group frames into (start_frame, end_frame_exclusive, pitch) runs."""
    out: list[tuple[int, int, int]] = []
    cur_pitch: int | None = None
    cur_start = 0
    for i in range(len(midi)):
        p = int(midi[i]) if voiced[i] else None
        split = cur_pitch is not None and p == cur_pitch and i in onset_frames
        if p != cur_pitch or split:
            if cur_pitch is not None:
                out.append((cur_start, i, cur_pitch))
            cur_pitch, cur_start = p, i
    if cur_pitch is not None:
        out.append((cur_start, len(midi), cur_pitch))
    return out


class PyinTranscriber(NoteTranscriber):
    name: ClassVar[str] = "pyin"
    version: ClassVar[str] = "1"
    polyphonic: ClassVar[bool] = False

    @classmethod
    def is_available(cls) -> bool:
        return True

    def transcribe(
        self, request: TranscriptionRequest, progress: ProgressFn = _noop
    ) -> list[NoteEvent]:
        if request.role == "harmony":
            progress(1.0)
            return []

        y = request.audio.mono_at(SR)
        if not np.any(np.abs(y) > 1e-4):
            progress(1.0)
            return []

        f0, voiced_flag, voiced_prob = librosa.pyin(
            y,
            fmin=max(request.min_hz, 30.0),
            fmax=min(request.max_hz, 2000.0),
            sr=SR,
            frame_length=FRAME,
            hop_length=HOP,
            fill_na=np.nan,
        )
        progress(0.7)

        voiced = voiced_flag & (voiced_prob >= VOICED_PROB) & np.isfinite(f0)
        midi = np.where(voiced, librosa.hz_to_midi(np.where(voiced, f0, 440.0)), 0.0)
        # Median smoothing removes single-frame octave slips and vibrato jitter.
        midi = np.round(scipy.ndimage.median_filter(midi, size=5)).astype(np.float64)
        voiced = voiced & (midi > 0)

        onset_env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
        onset_frames = set(
            librosa.onset.onset_detect(onset_envelope=onset_env, sr=SR, hop_length=HOP).tolist()
        )
        rms = librosa.feature.rms(y=y, frame_length=FRAME, hop_length=HOP)[0]
        rms_ref = float(np.percentile(rms[rms > 0], 95)) if np.any(rms > 0) else 1.0

        notes: list[NoteEvent] = []
        for s, e, pitch in _segments(midi, voiced, onset_frames):
            t0 = float(librosa.frames_to_time(s, sr=SR, hop_length=HOP))
            t1 = float(librosa.frames_to_time(e, sr=SR, hop_length=HOP))
            if t1 - t0 < MIN_NOTE_S or not 0 <= pitch <= 127:
                continue
            level = float(np.mean(rms[s : min(e, len(rms))])) / max(rms_ref, 1e-9)
            conf = float(np.mean(voiced_prob[s:e]))
            notes.append(
                NoteEvent(
                    start=t0,
                    end=t1,
                    pitch=pitch,
                    velocity=int(np.clip(40 + 70 * level, 1, 127)),
                    confidence=float(np.clip(conf, 0.0, 1.0)),
                )
            )
        progress(1.0)
        return notes

"""Sung-melody transcription: CREPE f0 + note segmentation.

CREPE (tiny model, Viterbi decoding) tracks the singer's pitch every 10 ms.
Frames are voiced when CREPE's periodicity and the signal level agree. Within
a voiced run a new note starts when the pitch leaves the running median of
the current note by more than DEVIATION_ST for MIN_DEVIATION_FRAMES frames
(a step to another note, not vibrato), or at a clear re-attack on the same
pitch. Each note's pitch is the median of its frames after the first 20 %
(skipping the scoop into the note).

Benchmark (bench/, 12 real sung melodies over a band, separated vocal stem):
note F1 at 50 ms 0.48 (Basic Pitch) -> 0.60; at 100 ms 0.57 -> 0.67. Runs
at about 0.1 s per minute of audio on CPU.

Monophonic: used for the melody of a vocal stem only.
"""

from __future__ import annotations

import importlib.util
from typing import ClassVar

import librosa
import numpy as np
import numpy.typing as npt
import scipy.ndimage

from pianoforge.analysis.interfaces import NoteTranscriber, ProgressFn, TranscriptionRequest, _noop
from pianoforge.analysis.ir import NoteEvent

SR = 16_000
HOP = 160  # 10 ms
FPS = SR / HOP
PERIODICITY = 0.4
LEVEL_GATE_DB = -35.0
DEVIATION_ST = 0.7
MIN_DEVIATION_FRAMES = 5
REATTACK = 1.2
MIN_NOTE_FRAMES = 6
HISTORY = 15


def segment_notes(
    midi: npt.NDArray[np.float64],
    voiced: npt.NDArray[np.bool_],
    reattack: npt.NDArray[np.float64],
) -> list[tuple[int, int, int]]:
    """(start_frame, end_frame, pitch) notes from a frame-wise pitch track."""
    notes: list[tuple[int, int, int]] = []
    n = len(midi)

    def close(a: int, b: int) -> None:
        if b - a < MIN_NOTE_FRAMES:
            return
        body = midi[a + (b - a) // 5 : b]
        notes.append((a, b, round(float(np.median(body)))))

    i = 0
    while i < n:
        if not voiced[i]:
            i += 1
            continue
        start = i
        hist = [float(midi[i])]
        dev = 0
        j = i + 1
        while j < n and voiced[j]:
            ref = float(np.median(hist[-HISTORY:]))
            dev = dev + 1 if abs(midi[j] - ref) > DEVIATION_ST else 0
            if dev >= MIN_DEVIATION_FRAMES:
                cut = j - MIN_DEVIATION_FRAMES + 1
                close(start, cut)
                start, hist, dev = cut, [float(x) for x in midi[cut : j + 1]], 0
            elif (
                reattack[j] > REATTACK
                and j - start > 2 * MIN_NOTE_FRAMES
                and abs(midi[j] - ref) < 0.5
                and reattack[j] >= reattack[max(start, j - 3) : j + 4].max()
            ):
                close(start, j)
                start, hist = j, [float(midi[j])]
            else:
                hist.append(float(midi[j]))
            j += 1
        close(start, j)
        i = j
    return notes


class CrepeTranscriber(NoteTranscriber):
    name: ClassVar[str] = "crepe"
    version: ClassVar[str] = "0.0.24-tiny"
    polyphonic: ClassVar[bool] = False

    @classmethod
    def is_available(cls) -> bool:
        return importlib.util.find_spec("torchcrepe") is not None

    def transcribe(
        self, request: TranscriptionRequest, progress: ProgressFn = _noop
    ) -> list[NoteEvent]:
        import torch
        import torchcrepe

        y = request.audio.mono_at(SR)
        if y.size < SR // 2:
            return []
        progress(0.05)
        f0, per = torchcrepe.predict(
            torch.from_numpy(np.ascontiguousarray(y))[None],
            SR,
            hop_length=HOP,
            fmin=max(50.0, request.min_hz),
            fmax=min(1500.0, request.max_hz),
            model="tiny",
            decoder=torchcrepe.decode.viterbi,
            return_periodicity=True,
            batch_size=1024,
            device="cpu",
        )
        progress(0.7)
        f0 = f0[0].numpy().astype(np.float64)
        per = scipy.ndimage.median_filter(per[0].numpy().astype(np.float64), 3)
        n = f0.size

        rms = librosa.feature.rms(y=y, frame_length=4 * HOP, hop_length=HOP)[0]
        rms = np.pad(rms, (0, max(0, n - rms.size)))[:n]
        gate = 10 ** (LEVEL_GATE_DB / 20) * float(np.percentile(rms, 95))
        voiced = (per > PERIODICITY) & (rms > gate)
        midi = scipy.ndimage.median_filter(69 + 12 * np.log2(np.maximum(f0, 1.0) / 440.0), 5)

        env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
        env = np.pad(env, (0, max(0, n - env.size)))[:n]
        reattack = env / (scipy.ndimage.percentile_filter(env, 90, size=300) + 1e-6)

        notes = []
        for a, b, pitch in segment_notes(midi, voiced, reattack):
            conf = float(np.mean(per[a:b]))
            level = float(np.mean(rms[a:b])) / (float(np.percentile(rms, 95)) + 1e-9)
            notes.append(
                NoteEvent(
                    start=round(a / FPS, 4),
                    end=round(b / FPS, 4),
                    pitch=int(np.clip(pitch, 0, 127)),
                    velocity=int(np.clip(40 + 80 * min(level, 1.0), 1, 127)),
                    confidence=round(min(max(conf, 0.0), 1.0), 3),
                )
            )
        progress(1.0)
        return notes

"""Stage functions of the analysis pipeline.

Pure with respect to infrastructure: they take audio buffers and a registry
and return typed parts. Celery tasks handle S3/DB I/O around them, which
keeps these functions directly unit-testable.
"""

from __future__ import annotations

from collections.abc import Mapping

import librosa
import numpy as np
import scipy.ndimage

from pianoforge.analysis.interfaces import (
    ProgressFn,
    SeparationResult,
    TonalInput,
    TranscriptionRequest,
    _noop,
)
from pianoforge.analysis.ir import KeyInfo, NoteEvent, NoteRole
from pianoforge.analysis.parts import RhythmPart, TonalPart, TrackPart, TranscriptionPart
from pianoforge.analysis.registry import AdapterRegistry, FallbackOutcome
from pianoforge.analysis.structure import segment_sections
from pianoforge.audio.buffer import AudioBuffer

ANALYSIS_SR = 22_050
AUDIBLE_STEM_DB = -45.0

ROLE_HZ: dict[NoteRole, tuple[float, float]] = {
    "melody": (80.0, 2000.0),
    "bass": (30.0, 400.0),
    "harmony": (60.0, 2500.0),
}


def _scaled(progress: ProgressFn, lo: float, hi: float) -> ProgressFn:
    return lambda f: progress(lo + (hi - lo) * max(0.0, min(1.0, f)))


def audible(buf: AudioBuffer | None) -> bool:
    return buf is not None and buf.rms_db() > AUDIBLE_STEM_DB


def _sum(buffers: list[tuple[AudioBuffer, float]], sr: int) -> AudioBuffer | None:
    parts = [(b.mono_at(sr), w) for b, w in buffers]
    if not parts:
        return None
    n = min(len(p) for p, _ in parts)
    y = np.zeros(n, dtype=np.float32)
    for p, w in parts:
        y += np.float32(w) * p[:n]
    return AudioBuffer.from_mono(y, sr)


# ------------------------------------------------------------------ separate
def run_separation(
    audio: AudioBuffer, registry: AdapterRegistry, progress: ProgressFn = _noop
) -> FallbackOutcome[SeparationResult]:
    return registry.separator.run(lambda a: a.separate(audio, progress))


# -------------------------------------------------------------------- rhythm
def beat_loudness(mix: AudioBuffer, beats: list[float]) -> list[float]:
    """Mean RMS level of each beat span in dB relative to the 95th percentile.

    Relative levels make dynamics independent of mastering loudness.
    """
    if len(beats) < 2:
        return []
    y = mix.mono_at(ANALYSIS_SR)
    hop = 512
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    if rms.size == 0:
        return []
    db = 20 * np.log10(np.maximum(rms, 1e-8))
    ref = float(np.percentile(db, 95))
    frames = np.clip((np.asarray(beats) * ANALYSIS_SR / hop).astype(int), 0, db.size - 1)
    out = []
    for i, f in enumerate(frames):
        g = frames[i + 1] if i + 1 < len(frames) else min(db.size, f + (f - frames[i - 1]))
        seg = db[f : max(g, f + 1)]
        out.append(round(float(np.mean(seg)) - ref, 2))
    return out


def run_rhythm(
    mix: AudioBuffer,
    stems: Mapping[str, AudioBuffer],
    registry: AdapterRegistry,
    progress: ProgressFn = _noop,
) -> RhythmPart:
    out = registry.beat_tracker.run(lambda a: a.track(mix, stems, progress))
    r = out.result
    warnings = list(out.warnings)
    if r.confidence < 0.3:
        warnings.append("rhythm: low beat confidence; tempo may be unstable")
    return RhythmPart(
        beat_loudness_db=beat_loudness(mix, [float(b) for b in r.beats]),
        engine=out.engine,
        bpm=float(r.bpm),
        beats=[float(b) for b in r.beats],
        downbeats=[float(b) for b in r.downbeats],
        time_signature=r.time_signature,
        confidence=float(r.confidence),
        tempo_curve=r.tempo_curve,
        warnings=warnings,
    )


# --------------------------------------------------------------------- tonal
def harmonic_source(mix: AudioBuffer, stems: Mapping[str, AudioBuffer]) -> AudioBuffer:
    """Pitched content without drums; vocals weighted down (melody, not harmony)."""
    parts: list[tuple[AudioBuffer, float]] = []
    for kind, weight in (("other", 1.0), ("bass", 0.7), ("vocals", 0.35)):
        buf = stems.get(kind)
        if audible(buf):
            assert buf is not None
            parts.append((buf, weight))
    summed = _sum(parts, ANALYSIS_SR)
    if summed is not None:
        return summed
    y = librosa.effects.harmonic(mix.mono_at(ANALYSIS_SR), margin=2.0)
    return AudioBuffer.from_mono(y, ANALYSIS_SR)


def run_tonal(
    mix: AudioBuffer,
    stems: Mapping[str, AudioBuffer],
    rhythm: RhythmPart,
    registry: AdapterRegistry,
    progress: ProgressFn = _noop,
) -> TonalPart:
    bass = stems.get("bass")
    data = TonalInput(
        harmonic=harmonic_source(mix, stems),
        bass=bass if audible(bass) else None,
        beats=np.asarray(rhythm.beats, dtype=np.float32),
        sample_rate=ANALYSIS_SR,
    )
    progress(0.1)
    key_out: FallbackOutcome[KeyInfo] = registry.key_detector.run(lambda a: a.detect(data))
    progress(0.3)
    chord_out = registry.chord_recognizer.run(
        lambda a: a.recognize(data, key_out.result, _scaled(progress, 0.3, 0.8))
    )
    sections = segment_sections(
        mix.mono_at(ANALYSIS_SR),
        np.asarray(rhythm.beats, dtype=np.float64),
        np.asarray(rhythm.downbeats, dtype=np.float64),
        mix.duration,
    )
    progress(1.0)
    warnings = [*key_out.warnings, *chord_out.warnings]
    if key_out.result.confidence < 0.2:
        warnings.append("key: ambiguous tonality")
    return TonalPart(
        key_engine=key_out.engine,
        chord_engine=chord_out.engine,
        key=key_out.result,
        chords=chord_out.result,
        sections=sections,
        warnings=warnings,
    )


# ------------------------------------------------------------- transcription
ATTACK_HOP = 256
# The vocal tracker must find at least this share of the general
# transcriber's notes (bench: real vocals >= 0.62, split vocals <= 0.36).
VOCAL_NOTE_RATIO = 0.5


def annotate_attacks(notes: list[NoteEvent], audio: AudioBuffer) -> list[NoteEvent]:
    """Attach the relative onset strength of ``audio`` at each note start.

    Onset strength is divided by its rolling 90th percentile over 3 s so the
    value is comparable across quiet and loud passages.
    """
    if not notes:
        return notes
    y = audio.mono_at(ANALYSIS_SR)
    env = librosa.onset.onset_strength(y=y, sr=ANALYSIS_SR, hop_length=ATTACK_HOP)
    if env.size == 0:
        return notes
    width = max(3, int(3.0 * ANALYSIS_SR / ATTACK_HOP))
    ref = scipy.ndimage.percentile_filter(env, 90, size=width) + 1e-6
    rel = env / ref
    out = []
    for n in notes:
        f = int(n.start * ANALYSIS_SR / ATTACK_HOP)
        seg = rel[max(0, f - 3) : f + 4]
        a = float(seg.max()) if seg.size else 0.0
        out.append(n.model_copy(update={"attack": round(a, 3)}))
    return out


def pick_sources(
    mix: AudioBuffer, stems: Mapping[str, AudioBuffer]
) -> dict[NoteRole, tuple[str, AudioBuffer]]:
    def first(*kinds: str) -> tuple[str, AudioBuffer]:
        for k in kinds:
            buf = stems.get(k)
            if audible(buf):
                assert buf is not None
                return k, buf
        return "mix", mix

    return {
        "melody": first("vocals", "other"),
        "bass": first("bass"),
        "harmony": first("other"),
    }


def run_transcription(
    mix: AudioBuffer,
    stems: Mapping[str, AudioBuffer],
    registry: AdapterRegistry,
    progress: ProgressFn = _noop,
) -> TranscriptionPart:
    sources = pick_sources(mix, stems)
    tracks: list[TrackPart] = []
    warnings: list[str] = []
    roles: list[NoteRole] = ["melody", "bass", "harmony"]
    for i, role in enumerate(roles):
        source_name, buf = sources[role]
        lo, hi = ROLE_HZ[role]
        req = TranscriptionRequest(audio=buf, role=role, min_hz=lo, max_hz=hi)
        step = _scaled(progress, i / len(roles), (i + 1) / len(roles))
        chain = (
            registry.vocal_transcriber
            if role == "melody" and source_name == "vocals"
            else registry.transcriber
        )
        out = chain.run(lambda a, r=req, p=step: a.transcribe(r, p))  # type: ignore[misc]
        notes = out.result
        if chain is registry.vocal_transcriber and not bool(
            getattr(out.adapter_cls, "polyphonic", True)
        ):
            # A monophonic tracker loses most of a vocal that the separator
            # split between stems (heavy effects, doubled voices). Cross-check
            # against the general transcriber and keep whichever sees the line.
            general = registry.transcriber.run(lambda a, r=req: a.transcribe(r))  # type: ignore[misc]
            if len(notes) < VOCAL_NOTE_RATIO * len(general.result):
                out, notes = general, general.result
                warnings.append("melody: weak vocal stem; used the polyphonic transcriber")
        # Instrumental track: vocals stem is audible noise but carries no melody.
        if (
            role == "melody"
            and source_name == "vocals"
            and len(notes) < 8
            and audible(stems.get("other"))
        ):
            other = stems["other"]
            req = TranscriptionRequest(audio=other, role=role, min_hz=lo, max_hz=hi)
            out = registry.transcriber.run(lambda a, r=req, p=step: a.transcribe(r, p))  # type: ignore[misc]
            notes, source_name = out.result, "other"
            warnings.append("melody: vocals near-silent; melody taken from accompaniment")
        warnings.extend(out.warnings)
        if role in ("melody", "bass"):
            notes = annotate_attacks(notes, stems.get(source_name, mix))
        polyphonic = bool(getattr(out.adapter_cls, "polyphonic", False))
        tracks.append(
            TrackPart(
                role=role, source=source_name, engine=out.engine, polyphonic=polyphonic, notes=notes
            )
        )
    progress(1.0)
    return TranscriptionPart(tracks=tracks, warnings=sorted(set(warnings), key=warnings.index))

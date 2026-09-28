"""Stages 3-4: rhythm -> (tonal || transcription) -> merge into AnalysisIR."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pianoforge.analysis.ir import PITCH_CLASS_NAMES, StemInfo
from pianoforge.analysis.merge import merge_analysis
from pianoforge.analysis.parts import RhythmPart, TonalPart, TranscriptionPart
from pianoforge.analysis.registry import get_registry
from pianoforge.analysis.service import run_rhythm, run_tonal, run_transcription
from pianoforge.config import get_settings
from pianoforge.db.enums import KeyMode, StemKind
from pianoforge.db.models import Analysis, Project, Stem
from pianoforge.db.session import sync_session
from pianoforge.storage import ObjectNotFound, get_storage
from pianoforge.storage import keys as K
from pianoforge.worker.base import PipelineTask
from pianoforge.worker.celery_app import celery_app
from pianoforge.worker.progress import ProgressReporter
from pianoforge.worker.tasks.common import load_mix, load_stems, part_key


def _cached_part(key: str) -> Any | None:
    try:
        return get_storage().get_json_gz(key)
    except ObjectNotFound:
        return None


@celery_app.task(base=PipelineTask, name="pianoforge.rhythm", bind=True)
def analyze_rhythm(self: PipelineTask, ctx: dict[str, Any]) -> dict[str, Any]:
    if ctx.get("cached"):
        return ctx
    key = part_key(ctx, "rhythm")
    reporter = ProgressReporter(ctx["job_id"], "rhythm")
    reporter.start()
    if _cached_part(key) is None:
        part = run_rhythm(load_mix(ctx), load_stems(ctx), get_registry(get_settings()), reporter)
        get_storage().put_json_gz(key, part.model_dump(mode="json"))
        reporter.event(f"템포 {part.bpm:.1f} BPM · {part.time_signature} 박자 ({part.engine})")
    reporter(1.0)
    return {**ctx, "rhythm_key": key}


@celery_app.task(base=PipelineTask, name="pianoforge.tonal", bind=True)
def analyze_tonal(self: PipelineTask, ctx: dict[str, Any]) -> dict[str, Any]:
    if ctx.get("cached"):
        return ctx
    key = part_key(ctx, "tonal")
    reporter = ProgressReporter(ctx["job_id"], "tonal")
    reporter.start()
    if _cached_part(key) is None:
        rhythm = RhythmPart.model_validate(get_storage().get_json_gz(ctx["rhythm_key"]))
        part = run_tonal(
            load_mix(ctx), load_stems(ctx), rhythm, get_registry(get_settings()), reporter
        )
        get_storage().put_json_gz(key, part.model_dump(mode="json"))
        reporter.event(
            f"조성 {part.key.name} · 코드 {len(part.chords)}개 · 섹션 {len(part.sections)}개"
        )
    reporter(1.0)
    return {**ctx, "tonal_key": key}


@celery_app.task(base=PipelineTask, name="pianoforge.transcribe", bind=True)
def transcribe_notes(self: PipelineTask, ctx: dict[str, Any]) -> dict[str, Any]:
    if ctx.get("cached"):
        return ctx
    key = part_key(ctx, "transcription")
    reporter = ProgressReporter(ctx["job_id"], "transcribe")
    reporter.start()
    if _cached_part(key) is None:
        part = run_transcription(
            load_mix(ctx), load_stems(ctx), get_registry(get_settings()), reporter
        )
        get_storage().put_json_gz(key, part.model_dump(mode="json"))
        counts = ", ".join(f"{t.role} {len(t.notes)}" for t in part.tracks)
        reporter.event(f"음표 추출: {counts}")
    reporter(1.0)
    return {**ctx, "transcription_key": key}


@celery_app.task(base=PipelineTask, name="pianoforge.merge", bind=True)
def merge_parts(self: PipelineTask, results: list[dict[str, Any]]) -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    for r in results:
        ctx.update(r)
    if ctx.get("cached"):
        return ctx

    storage = get_storage()
    reporter = ProgressReporter(ctx["job_id"], "merge")
    reporter.start()
    rhythm = RhythmPart.model_validate(storage.get_json_gz(ctx["rhythm_key"]))
    tonal = TonalPart.model_validate(storage.get_json_gz(ctx["tonal_key"]))
    transcription = TranscriptionPart.model_validate(storage.get_json_gz(ctx["transcription_key"]))
    stems = [StemInfo.model_validate(s) for s in ctx["stems"]]

    ir = merge_analysis(
        pipeline_version=ctx["pipeline_version"],
        duration=float(ctx["duration"]),
        sample_rate=int(ctx["sample_rate"]),
        separator_engine=ctx["separator_engine"],
        stems=stems,
        rhythm=rhythm,
        tonal=tonal,
        transcription=transcription,
        extra_warnings=ctx.get("separator_warnings", []),
    )
    reporter(0.5)
    asset_id = uuid.UUID(ctx["asset_id"])
    ir_key = K.analysis_ir(asset_id, ctx["pipeline_version"])
    storage.put_json_gz(ir_key, ir.model_dump(mode="json"))

    analysis_id = _persist_analysis(ctx, ir_key, ir, stems)
    key_name = f"{PITCH_CLASS_NAMES[ir.key.tonic]} {ir.key.mode}"
    reporter.event(
        f"분석 완료: {key_name} · {ir.tempo.bpm:.0f} BPM · {ir.time_signature}"
        f" · 경고 {len(ir.warnings)}건"
    )
    reporter(1.0)
    return {**ctx, "analysis_id": str(analysis_id)}


def _persist_analysis(
    ctx: dict[str, Any], ir_key: str, ir: Any, stems: list[StemInfo]
) -> uuid.UUID:
    asset_id = uuid.UUID(ctx["asset_id"])
    try:
        with sync_session() as s:
            analysis = Analysis(
                audio_asset_id=asset_id,
                pipeline_version=ctx["pipeline_version"],
                engine_versions=ir.engines,
                tempo_bpm=ir.tempo.bpm,
                time_signature=str(ir.time_signature),
                key_tonic=ir.key.tonic,
                key_mode=KeyMode(ir.key.mode),
                key_confidence=ir.key.confidence,
                summary=ir.summary(),
                ir_key=ir_key,
            )
            analysis.stems = [
                Stem(
                    kind=StemKind(st.kind),
                    engine=st.engine,
                    storage_key=st.storage_key,
                    rms_db=st.rms_db,
                )
                for st in stems
            ]
            s.add(analysis)
            s.flush()
            analysis_id = analysis.id
            _link_project(s, ctx, analysis_id)
    except IntegrityError:
        # Another job analysed the same asset concurrently; use its row.
        with sync_session() as s:
            analysis_id = s.execute(
                select(Analysis.id).where(
                    Analysis.audio_asset_id == asset_id,
                    Analysis.pipeline_version == ctx["pipeline_version"],
                )
            ).scalar_one()
            _link_project(s, ctx, analysis_id)
    return analysis_id


def _link_project(s: Any, ctx: dict[str, Any], analysis_id: uuid.UUID) -> None:
    project = s.get(Project, uuid.UUID(ctx["project_id"]))
    if project is not None:
        project.current_analysis_id = analysis_id

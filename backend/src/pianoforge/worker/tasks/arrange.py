"""Stage 5: AnalysisIR -> ScoreIR for the job's ArrangementParams."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from pianoforge.analysis.ir import AnalysisIR
from pianoforge.arrangement.engine import arrange
from pianoforge.arrangement.params import ArrangementParams
from pianoforge.db.enums import ArrangementStatus, ExportFormat
from pianoforge.db.models import Analysis, Arrangement, Project
from pianoforge.db.session import sync_session
from pianoforge.storage import get_storage
from pianoforge.storage import keys as K
from pianoforge.worker.base import PipelineTask
from pianoforge.worker.celery_app import celery_app
from pianoforge.worker.progress import ProgressReporter

DIFFICULTY_KO = {"beginner": "초급", "intermediate": "중급", "advanced": "고급"}


def _get_or_create(
    project_id: uuid.UUID, analysis_id: uuid.UUID, params: ArrangementParams
) -> Arrangement:
    params_hash = params.canonical_hash()
    with sync_session() as s:
        row = s.execute(
            select(Arrangement).where(
                Arrangement.project_id == project_id,
                Arrangement.analysis_id == analysis_id,
                Arrangement.difficulty == params.difficulty,
                Arrangement.params_hash == params_hash,
            )
        ).scalar_one_or_none()
        if row is not None:
            return row
    try:
        with sync_session() as s:
            revision = (
                s.execute(
                    select(func.count(Arrangement.id)).where(Arrangement.project_id == project_id)
                ).scalar_one()
                + 1
            )
            row = Arrangement(
                project_id=project_id,
                analysis_id=analysis_id,
                difficulty=params.difficulty,
                params=params.model_dump(mode="json"),
                params_hash=params_hash,
                revision=revision,
                status=ArrangementStatus.pending,
            )
            s.add(row)
            s.flush()
            return row
    except IntegrityError:
        # A concurrent job created the same arrangement; use it.
        return _get_or_create(project_id, analysis_id, params)


def mark_arrangement_failed(arrangement_id: str | None) -> None:
    if not arrangement_id:
        return
    with sync_session() as s:
        row = s.get(Arrangement, uuid.UUID(arrangement_id))
        if row is not None and row.status != ArrangementStatus.ready:
            row.status = ArrangementStatus.failed


@celery_app.task(base=PipelineTask, name="pianoforge.arrange", bind=True)
def arrange_score(self: PipelineTask, ctx: dict[str, Any]) -> dict[str, Any]:
    kind = ctx.get("kind", "full")
    reporter = ProgressReporter(ctx["job_id"], "arrange", kind=kind)
    reporter.start()
    params = ArrangementParams.model_validate(ctx.get("params") or {})
    analysis_id = uuid.UUID(ctx["analysis_id"])
    project_id = uuid.UUID(ctx["project_id"])

    with sync_session() as s:
        analysis = s.get(Analysis, analysis_id)
        project = s.get(Project, project_id)
        if analysis is None or project is None:
            raise LookupError("analysis or project missing")
        ir_key, title = analysis.ir_key, project.title

    row = _get_or_create(project_id, analysis_id, params)
    ctx = {**ctx, "arrangement_id": str(row.id)}
    if row.status == ArrangementStatus.ready and {e.format for e in row.exports} >= set(
        ExportFormat
    ):
        reporter.event("같은 설정의 편곡을 재사용합니다")
        reporter(1.0)
        return {**ctx, "arrangement_cached": True}

    storage = get_storage()
    try:
        ir = AnalysisIR.model_validate(storage.get_json_gz(ir_key))
        reporter(0.2)
        score = arrange(ir, params, title)
        reporter(0.8)
        score_key = K.score_ir(row.id)
        storage.put_json_gz(score_key, score.model_dump(mode="json"))
        with sync_session() as s:
            db_row = s.get(Arrangement, row.id)
            assert db_row is not None
            db_row.score_ir_key = score_key
            db_row.stats = {**score.stats, "measures": score.measures, "key": score.key.name,
                            "tempo_bpm": score.tempo_bpm, "warnings": score.warnings}  # fmt: skip
    except Exception:
        mark_arrangement_failed(ctx["arrangement_id"])
        raise

    st = score.stats
    reporter.event(
        f"{DIFFICULTY_KO[score.difficulty]} 편곡: {score.measures}마디 · {score.key.name} · "
        f"패턴 {st['pattern']} · 오른손 {st['rh_notes']}음 / 왼손 {st['lh_notes']}음 · "
        f"난이도 지수 {st['difficulty_score']}"
    )
    for w in score.warnings:
        reporter.event(w, level="warn")
    reporter(1.0)
    return ctx

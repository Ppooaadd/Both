"""Arrangements: re-arrange with new parameters, inspect scores, download exports."""

from __future__ import annotations

import re
import uuid
from decimal import Decimal
from typing import Any

import anyio
from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pianoforge.api.deps import CurrentUser, DbDep, SettingsDep, StorageDep, user_rate_limit
from pianoforge.api.errors import Conflict, NotFound, ServiceUnavailable, TooManyRequests
from pianoforge.api.routers.projects import ACTIVE, owned_project
from pianoforge.api.schemas import (
    ArrangementCreateIn,
    ArrangementDetailOut,
    ArrangementOut,
    ArrangementRequestOut,
    DownloadOut,
    JobOut,
)
from pianoforge.db.enums import ArrangementStatus, ExportFormat, JobKind, JobStatus, Plan, UsageKind
from pianoforge.db.models import Arrangement, Job, Project, UsageRecord, User
from pianoforge.export.formats import CONTENT_TYPES, EXTENSIONS
from pianoforge.logging import get_logger
from pianoforge.storage import ObjectNotFound
from pianoforge.worker.pipeline import enqueue_rearrange, initial_context

log = get_logger(__name__)
router = APIRouter(tags=["arrangements"])

DIFFICULTY_LABEL = {"beginner": "Beginner", "intermediate": "Intermediate", "advanced": "Advanced"}


async def owned_arrangement(db: AsyncSession, user: User, arrangement_id: uuid.UUID) -> Arrangement:
    row = (
        await db.execute(
            select(Arrangement)
            .join(Project, Project.id == Arrangement.project_id)
            .where(Arrangement.id == arrangement_id, Project.user_id == user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("편곡을 찾을 수 없습니다.")
    return row


def _safe_filename(title: str, difficulty: str, fmt: str) -> str:
    base = re.sub(r"[^\w\s.-]", "", title, flags=re.UNICODE).strip() or "PianoForge"
    return f"{base[:80]} ({DIFFICULTY_LABEL[difficulty]}).{EXTENSIONS[fmt]}"


@router.post(
    "/projects/{project_id}/arrangements",
    response_model=ArrangementRequestOut,
    dependencies=[Depends(user_rate_limit("arrangements.create"))],
    responses={202: {"model": ArrangementRequestOut}},
)
async def request_arrangement(
    project_id: uuid.UUID,
    body: ArrangementCreateIn,
    user: CurrentUser,
    db: DbDep,
    settings: SettingsDep,
) -> JSONResponse:
    project = await owned_project(db, user, project_id)
    if project.current_analysis_id is None:
        raise Conflict("분석이 끝난 뒤에 편곡할 수 있습니다.", code="analysis_not_ready")
    params = body.params
    existing = (
        await db.execute(
            select(Arrangement).where(
                Arrangement.project_id == project.id,
                Arrangement.analysis_id == project.current_analysis_id,
                Arrangement.difficulty == params.difficulty,
                Arrangement.params_hash == params.canonical_hash(),
                Arrangement.status == ArrangementStatus.ready,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        out = ArrangementRequestOut(arrangement=ArrangementOut.model_validate(existing), job=None)
        return JSONResponse(out.model_dump(mode="json"), status_code=status.HTTP_200_OK)

    limit = (
        settings.max_concurrent_jobs_pro
        if user.plan == Plan.pro
        else settings.max_concurrent_jobs_free
    )
    active = (
        await db.execute(
            select(func.count(Job.id))
            .join(Project, Project.id == Job.project_id)
            .where(Project.user_id == user.id, Job.status.in_(ACTIVE))
        )
    ).scalar_one()
    if active >= limit:
        raise TooManyRequests(
            f"동시에 처리할 수 있는 작업은 최대 {limit}개입니다.", code="too_many_active_jobs"
        )

    job = Job(project_id=project.id, kind=JobKind.rearrange, params=params.model_dump(mode="json"))
    db.add(job)
    db.add(UsageRecord(user_id=user.id, kind=UsageKind.rearrange, amount=Decimal(1)))
    await db.commit()
    ctx = initial_context(
        job_id=job.id,
        project_id=project.id,
        user_id=user.id,
        asset_id=project.audio_asset_id,
        params=job.params,
        kind="rearrange",
        analysis_id=project.current_analysis_id,
    )
    try:
        job.celery_root_id = await anyio.to_thread.run_sync(enqueue_rearrange, ctx)
    except Exception as e:
        log.exception("enqueue_failed", job_id=str(job.id))
        job.status = JobStatus.failed
        job.error_code = "enqueue_failed"
        job.error_message = "작업 대기열에 등록하지 못했습니다."
        await db.commit()
        raise ServiceUnavailable(
            "작업 대기열에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."
        ) from e
    await db.commit()
    await db.refresh(job)
    out = ArrangementRequestOut(arrangement=None, job=JobOut.model_validate(job))
    return JSONResponse(out.model_dump(mode="json"), status_code=status.HTTP_202_ACCEPTED)


@router.get("/projects/{project_id}/arrangements", response_model=list[ArrangementOut])
async def list_arrangements(
    project_id: uuid.UUID, user: CurrentUser, db: DbDep
) -> list[Arrangement]:
    project = await owned_project(db, user, project_id)
    rows = await db.execute(
        select(Arrangement)
        .where(Arrangement.project_id == project.id)
        .order_by(Arrangement.created_at.desc())
    )
    return list(rows.scalars())


@router.get("/arrangements/{arrangement_id}", response_model=ArrangementDetailOut)
async def get_arrangement(
    arrangement_id: uuid.UUID,
    user: CurrentUser,
    db: DbDep,
    storage: StorageDep,
    include_score: bool = Query(default=True),
) -> ArrangementDetailOut:
    row = await owned_arrangement(db, user, arrangement_id)
    out = ArrangementDetailOut.model_validate(row)
    if include_score and row.score_ir_key:
        try:
            score: dict[str, Any] = await anyio.to_thread.run_sync(
                storage.get_json_gz, row.score_ir_key
            )
        except ObjectNotFound:
            score = None  # type: ignore[assignment]
        out.score = score
    return out


@router.get("/arrangements/{arrangement_id}/exports/{fmt}", response_model=DownloadOut)
async def download_export(
    arrangement_id: uuid.UUID,
    fmt: ExportFormat,
    user: CurrentUser,
    db: DbDep,
    settings: SettingsDep,
    storage: StorageDep,
    redirect: bool = Query(default=True),
) -> Response:
    row = await owned_arrangement(db, user, arrangement_id)
    export = next((e for e in row.exports if e.format == fmt), None)
    if export is None:
        raise NotFound("아직 이 형식의 파일이 준비되지 않았습니다.", code="export_not_ready")
    project = await db.get(Project, row.project_id)
    assert project is not None
    filename = _safe_filename(project.title, row.difficulty.value, fmt.value)
    url = storage.presign_download(export.storage_key, filename, CONTENT_TYPES[fmt.value])
    if redirect:
        return RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    return JSONResponse(
        DownloadOut(url=url, expires_in=settings.download_url_ttl_s, filename=filename).model_dump()
    )

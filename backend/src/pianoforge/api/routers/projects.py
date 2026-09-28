"""Projects: confirm an upload and start the pipeline; list, inspect, rename, delete."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

import anyio
from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pianoforge.api.deps import (
    CurrentUser,
    DbDep,
    RedisDep,
    SettingsDep,
    StorageDep,
    user_rate_limit,
)
from pianoforge.api.errors import (
    Conflict,
    NotFound,
    PayloadTooLarge,
    ServiceUnavailable,
    TooManyRequests,
)
from pianoforge.api.routers.jobs import cancel_job_rows
from pianoforge.api.schemas import (
    AnalysisSummaryOut,
    ArrangementOut,
    AssetOut,
    JobOut,
    Page,
    ProjectCreatedOut,
    ProjectCreateIn,
    ProjectDetailOut,
    ProjectOut,
    ProjectUpdateIn,
)
from pianoforge.db.enums import AssetStatus, JobKind, JobStatus, Plan
from pianoforge.db.models import Arrangement, AudioAsset, Job, Project, User
from pianoforge.logging import get_logger
from pianoforge.storage import ObjectNotFound
from pianoforge.worker.celery_app import celery_app
from pianoforge.worker.pipeline import enqueue_full_pipeline, initial_context

log = get_logger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])

ACTIVE = (JobStatus.queued, JobStatus.running)


async def owned_project(db: AsyncSession, user: User, project_id: uuid.UUID) -> Project:
    project = (
        await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == user.id)
        )
    ).scalar_one_or_none()
    if project is None:
        raise NotFound("프로젝트를 찾을 수 없습니다.")
    return project


async def latest_jobs(db: AsyncSession, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, Job]:
    if not project_ids:
        return {}
    rows = (
        await db.execute(
            select(Job)
            .where(Job.project_id.in_(project_ids))
            .distinct(Job.project_id)
            .order_by(Job.project_id, Job.created_at.desc())
        )
    ).scalars()
    return {j.project_id: j for j in rows}


def _project_out(p: Project, job: Job | None) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        title=p.title,
        created_at=p.created_at,
        updated_at=p.updated_at,
        latest_job=JobOut.model_validate(job) if job else None,
    )


def _encode_cursor(created_at: datetime, pid: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{pid}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        ts, pid = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
        return datetime.fromisoformat(ts), uuid.UUID(pid)
    except (ValueError, UnicodeDecodeError) as e:
        raise NotFound("잘못된 페이지 커서입니다.", code="invalid_cursor") from e


@router.post(
    "",
    response_model=ProjectCreatedOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(user_rate_limit("projects.create"))],
)
async def create_project(
    body: ProjectCreateIn, user: CurrentUser, db: DbDep, settings: SettingsDep, storage: StorageDep
) -> ProjectCreatedOut:
    asset = (
        await db.execute(
            select(AudioAsset)
            .where(AudioAsset.id == body.upload_id, AudioAsset.user_id == user.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if asset is None:
        raise NotFound("업로드를 찾을 수 없습니다.")
    in_use = (
        await db.execute(select(Project.id).where(Project.audio_asset_id == asset.id).limit(1))
    ).first()
    # "uploaded" without a project means an earlier attempt failed to enqueue; allow retry.
    if asset.status not in (AssetStatus.pending, AssetStatus.uploaded) or in_use:
        raise Conflict("이미 사용되었거나 거부된 업로드입니다.", code="upload_consumed")

    try:
        info = await anyio.to_thread.run_sync(storage.head, asset.storage_key)
    except ObjectNotFound as e:
        raise Conflict("업로드가 아직 완료되지 않았습니다.", code="upload_incomplete") from e
    if info.size > settings.upload_max_bytes:
        raise PayloadTooLarge("파일 크기 제한을 초과했습니다.")

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
            f"동시에 처리할 수 있는 작업은 최대 {limit}개입니다. "
            "진행 중인 작업이 끝난 뒤 다시 시도해 주세요.",
            code="too_many_active_jobs",
        )

    asset.status = AssetStatus.uploaded
    asset.size_bytes = info.size
    title = body.title or PurePosixPath(asset.original_filename).stem[:200] or "Untitled"
    project = Project(user_id=user.id, audio_asset_id=asset.id, title=title)
    db.add(project)
    await db.flush()
    params = body.params.model_dump(mode="json")
    job = Job(project_id=project.id, kind=JobKind.full, params=params)
    db.add(job)
    await db.commit()

    ctx = initial_context(
        job_id=job.id, project_id=project.id, user_id=user.id, asset_id=asset.id, params=params
    )
    try:
        root_id = await anyio.to_thread.run_sync(enqueue_full_pipeline, ctx)
    except Exception as e:
        log.exception("enqueue_failed", job_id=str(job.id))
        job.status = JobStatus.failed
        job.error_code = "enqueue_failed"
        job.error_message = "작업 대기열에 등록하지 못했습니다."
        await db.commit()
        raise ServiceUnavailable(
            "작업 대기열에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."
        ) from e

    job.celery_root_id = root_id
    await db.commit()
    await db.refresh(job)
    await db.refresh(project)
    return ProjectCreatedOut(project=_project_out(project, job), job=JobOut.model_validate(job))


@router.get("", response_model=Page[ProjectOut])
async def list_projects(
    user: CurrentUser,
    db: DbDep,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
) -> Page[ProjectOut]:
    stmt = select(Project).where(Project.user_id == user.id)
    if cursor:
        ts, pid = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(Project.created_at < ts, and_(Project.created_at == ts, Project.id < pid))
        )
    rows = list(
        (
            await db.execute(
                stmt.order_by(Project.created_at.desc(), Project.id.desc()).limit(limit + 1)
            )
        ).scalars()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    jobs = await latest_jobs(db, [p.id for p in rows])
    return Page[ProjectOut](
        items=[_project_out(p, jobs.get(p.id)) for p in rows],
        next_cursor=_encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None,
    )


@router.get("/{project_id}", response_model=ProjectDetailOut)
async def get_project(project_id: uuid.UUID, user: CurrentUser, db: DbDep) -> ProjectDetailOut:
    project = await owned_project(db, user, project_id)
    jobs = await latest_jobs(db, [project.id])
    base = _project_out(project, jobs.get(project.id))
    latest = (
        await db.execute(
            select(Arrangement)
            .where(Arrangement.project_id == project.id)
            .order_by(Arrangement.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return ProjectDetailOut(
        **base.model_dump(),
        latest_arrangement=ArrangementOut.model_validate(latest) if latest else None,
        asset=AssetOut.model_validate(project.audio_asset),
        analysis=AnalysisSummaryOut.model_validate(project.current_analysis)
        if project.current_analysis
        else None,
    )


@router.get("/{project_id}/analysis")
async def get_analysis(
    project_id: uuid.UUID, user: CurrentUser, db: DbDep, storage: StorageDep
) -> JSONResponse:
    """Full AnalysisIR (beats, chords, sections, note tracks) for the UI."""
    project = await owned_project(db, user, project_id)
    if project.current_analysis is None:
        raise NotFound("아직 분석 결과가 없습니다.", code="analysis_not_ready")
    try:
        ir: dict[str, Any] = await anyio.to_thread.run_sync(
            storage.get_json_gz, project.current_analysis.ir_key
        )
    except ObjectNotFound as e:
        raise NotFound("분석 결과 파일을 찾을 수 없습니다.", code="analysis_missing") from e
    return JSONResponse(
        {"analysis_id": str(project.current_analysis.id), "ir": ir},
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.patch("/{project_id}", response_model=ProjectOut)
async def rename_project(
    project_id: uuid.UUID, body: ProjectUpdateIn, user: CurrentUser, db: DbDep
) -> ProjectOut:
    project = await owned_project(db, user, project_id)
    project.title = body.title
    await db.commit()
    await db.refresh(project)
    jobs = await latest_jobs(db, [project.id])
    return _project_out(project, jobs.get(project.id))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID, user: CurrentUser, db: DbDep, redis: RedisDep
) -> Response:
    project = await owned_project(db, user, project_id)
    active = list(
        (
            await db.execute(
                select(Job).where(Job.project_id == project.id, Job.status.in_(ACTIVE))
            )
        ).scalars()
    )
    await cancel_job_rows(db, redis, active)
    asset_id = str(project.audio_asset_id)
    await db.delete(project)
    await db.commit()
    # Storage cleanup runs only if no other project references the asset.
    await anyio.to_thread.run_sync(
        lambda: celery_app.send_task(
            "pianoforge.maintenance.delete_asset", args=[asset_id], countdown=5
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

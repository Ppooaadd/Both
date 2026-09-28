"""Job status (polling fallback for the WebSocket), event log, cancellation."""

from __future__ import annotations

import functools
import uuid
from datetime import UTC, datetime

import anyio
from fastapi import APIRouter, Query
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pianoforge.api.deps import CurrentUser, DbDep, RedisDep
from pianoforge.api.errors import Conflict, NotFound
from pianoforge.api.schemas import JobEventOut, JobOut
from pianoforge.db.enums import JobStatus
from pianoforge.db.models import Job, JobEvent, Project, User
from pianoforge.events import channel, encode
from pianoforge.logging import get_logger
from pianoforge.worker.celery_app import celery_app

log = get_logger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])


async def owned_job(db: AsyncSession, user: User, job_id: uuid.UUID) -> Job:
    job = (
        await db.execute(
            select(Job)
            .join(Project, Project.id == Job.project_id)
            .where(Job.id == job_id, Project.user_id == user.id)
        )
    ).scalar_one_or_none()
    if job is None:
        raise NotFound("작업을 찾을 수 없습니다.")
    return job


async def cancel_job_rows(db: AsyncSession, redis: Redis, jobs: list[Job]) -> None:
    """Mark jobs canceled, revoke their queued root task, notify subscribers.

    Running tasks stop at their next progress update (cooperative cancellation);
    later chain steps see the canceled status and are ignored.
    """
    now = datetime.now(UTC)
    for job in jobs:
        if job.status not in (JobStatus.queued, JobStatus.running):
            continue
        job.status = JobStatus.canceled
        job.finished_at = now
    await db.commit()
    for job in jobs:
        if job.celery_root_id:
            root_id = job.celery_root_id
            try:
                await anyio.to_thread.run_sync(
                    functools.partial(celery_app.control.revoke, root_id)
                )
            except Exception as exc:
                log.warning("revoke_failed", job_id=str(job.id), error=repr(exc))
        try:
            await redis.publish(
                channel(job.id),
                encode(
                    {
                        "type": "status",
                        "job_id": str(job.id),
                        "status": "canceled",
                        "stage": job.stage,
                        "progress": job.progress,
                    }
                ),
            )
        except RedisError as exc:
            log.warning("cancel_publish_failed", job_id=str(job.id), error=repr(exc))


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, user: CurrentUser, db: DbDep) -> Job:
    return await owned_job(db, user, job_id)


@router.get("/{job_id}/events", response_model=list[JobEventOut])
async def list_events(
    job_id: uuid.UUID,
    user: CurrentUser,
    db: DbDep,
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[JobEvent]:
    await owned_job(db, user, job_id)
    rows = await db.execute(
        select(JobEvent)
        .where(JobEvent.job_id == job_id, JobEvent.id > after_id)
        .order_by(JobEvent.id)
        .limit(limit)
    )
    return list(rows.scalars())


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(job_id: uuid.UUID, user: CurrentUser, db: DbDep, redis: RedisDep) -> Job:
    job = await owned_job(db, user, job_id)
    if job.status not in (JobStatus.queued, JobStatus.running):
        raise Conflict("이미 종료된 작업입니다.", code="job_finished")
    await cancel_job_rows(db, redis, [job])
    await db.refresh(job)
    return job

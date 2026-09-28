"""Progress reporting from tasks: DB row update + job_events + Redis publish.

``ProgressReporter`` doubles as a cooperative cancellation point: the job row
is only updated while it is queued/running, so an update that touches no row
means the job was canceled or already failed, and ``JobStopped`` is raised.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import redis
from sqlalchemy import text

from pianoforge.analysis.interfaces import Interrupted
from pianoforge.config import get_settings
from pianoforge.db.session import sync_session
from pianoforge.events import channel, encode, overall
from pianoforge.logging import get_logger

log = get_logger(__name__)


class JobStopped(Interrupted):
    """The job is no longer active (canceled or failed elsewhere); stop quietly."""


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def reset_redis() -> None:
    get_redis.cache_clear()


def publish(job_id: uuid.UUID | str, payload: dict[str, Any]) -> None:
    try:
        get_redis().publish(channel(job_id), encode(payload))
    except redis.RedisError as exc:
        # Progress push is best-effort; the DB row stays authoritative for polling.
        log.warning("progress_publish_failed", job_id=str(job_id), error=repr(exc))


_UPDATE_SQL = text(
    """
    UPDATE jobs
       SET stage = :stage,
           progress = GREATEST(progress, :progress),
           status = 'running',
           started_at = COALESCE(started_at, now())
     WHERE id = :id AND status IN ('queued', 'running')
    RETURNING progress
    """
)

_EVENT_SQL = text(
    """
    INSERT INTO job_events (job_id, stage, progress, level, message)
    VALUES (:job_id, :stage, :progress, CAST(:level AS event_level), :message)
    RETURNING id, created_at
    """
)


class ProgressReporter:
    def __init__(self, job_id: uuid.UUID | str, stage: str, min_interval_s: float = 1.0) -> None:
        self.job_id = str(job_id)
        self.stage = stage
        self.min_interval_s = min_interval_s
        self._last_sent = 0.0
        self._last_pct = -1

    def start(self, message: str | None = None) -> None:
        self.update(0.0, force=True)
        if message:
            self.event(message)

    def __call__(self, fraction: float) -> None:
        self.update(fraction)

    def update(self, fraction: float, force: bool = False) -> None:
        pct = overall(self.stage, fraction)
        now = time.monotonic()
        if not force and (pct == self._last_pct or now - self._last_sent < self.min_interval_s):
            return
        with sync_session() as s:
            row = s.execute(
                _UPDATE_SQL, {"id": self.job_id, "stage": self.stage, "progress": pct}
            ).first()
        if row is None:
            raise JobStopped(self.job_id)
        self._last_sent, self._last_pct = now, pct
        publish(
            self.job_id,
            {
                "type": "progress",
                "job_id": self.job_id,
                "stage": self.stage,
                "progress": int(row[0]),
                "status": "running",
            },
        )

    def event(self, message: str, level: str = "info") -> None:
        pct = max(self._last_pct, 0)
        with sync_session() as s:
            row = s.execute(
                _EVENT_SQL,
                {
                    "job_id": self.job_id,
                    "stage": self.stage,
                    "progress": pct,
                    "level": level,
                    "message": message[:2000],
                },
            ).one()
        publish(
            self.job_id,
            {
                "type": "event",
                "job_id": self.job_id,
                "id": int(row[0]),
                "stage": self.stage,
                "progress": pct,
                "level": level,
                "message": message,
                "created_at": row[1].isoformat(),
            },
        )


def mark_succeeded(job_id: uuid.UUID | str, extra: dict[str, Any] | None = None) -> bool:
    with sync_session() as s:
        row = s.execute(
            text(
                """
                UPDATE jobs SET status = 'succeeded', stage = 'done', progress = 100,
                       finished_at = now(), error_code = NULL, error_message = NULL
                 WHERE id = :id AND status IN ('queued', 'running')
                RETURNING id
                """
            ),
            {"id": str(job_id)},
        ).first()
    if row is None:
        return False
    publish(
        job_id,
        {
            "type": "status",
            "job_id": str(job_id),
            "status": "succeeded",
            "stage": "done",
            "progress": 100,
            **(extra or {}),
        },
    )
    return True


def mark_failed(job_id: uuid.UUID | str, code: str, message: str) -> bool:
    with sync_session() as s:
        row = s.execute(
            text(
                """
                UPDATE jobs SET status = 'failed', finished_at = now(),
                       error_code = :code, error_message = :message
                 WHERE id = :id AND status IN ('queued', 'running')
                RETURNING stage, progress
                """
            ),
            {"id": str(job_id), "code": code, "message": message[:2000]},
        ).first()
        if row is not None:
            s.execute(
                _EVENT_SQL,
                {
                    "job_id": str(job_id),
                    "stage": row[0],
                    "progress": row[1],
                    "level": "error",
                    "message": message[:2000],
                },
            )
    if row is None:
        return False
    publish(
        job_id,
        {
            "type": "status",
            "job_id": str(job_id),
            "status": "failed",
            "stage": row[0],
            "progress": int(row[1]),
            "error_code": code,
            "error_message": message,
            "at": datetime.now(UTC).isoformat(),
        },
    )
    return True

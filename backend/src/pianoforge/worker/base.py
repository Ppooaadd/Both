"""Base task class for pipeline stages.

* retries transient infrastructure errors with exponential backoff
* marks the job failed (with a user-safe message) on final failure
* turns cooperative cancellation (``JobStopped``) into ``Ignore`` so the rest
  of the chain is dropped without marking anything failed
"""

from __future__ import annotations

from typing import Any

import redis
from botocore.exceptions import BotoCoreError, ConnectionClosedError, EndpointConnectionError
from celery import Task
from celery.exceptions import Ignore, SoftTimeLimitExceeded
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError

from pianoforge.analysis.registry import NoAdapterAvailable, register_propagating
from pianoforge.audio.probe import AudioValidationError
from pianoforge.db.session import sync_session
from pianoforge.logging import get_logger
from pianoforge.worker import files
from pianoforge.worker.progress import JobStopped, mark_failed

log = get_logger(__name__)

# A soft time limit must stop the stage, not start the next (slower) engine.
register_propagating(SoftTimeLimitExceeded)

TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    OperationalError,
    EndpointConnectionError,
    ConnectionClosedError,
    redis.ConnectionError,
    redis.TimeoutError,
)


def job_id_from_args(args: tuple[Any, ...]) -> str | None:
    """Pipeline tasks take ``ctx`` (dict) or, for chord callbacks, ``[ctx, ...]``."""
    if not args:
        return None
    first = args[0]
    if isinstance(first, dict):
        return first.get("job_id")
    if isinstance(first, list) and first and isinstance(first[0], dict):
        return first[0].get("job_id")
    return None


def user_error(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, AudioValidationError):
        return exc.code, exc.message
    if isinstance(exc, SoftTimeLimitExceeded):
        return "timeout", "처리 시간이 제한을 초과했습니다. 더 짧은 곡으로 다시 시도해 주세요."
    if isinstance(exc, NoAdapterAvailable):
        return "engine_unavailable", "분석 엔진을 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."
    if isinstance(exc, (BotoCoreError, DBAPIError, redis.RedisError)):
        return "infrastructure", "일시적인 서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
    return "internal_error", "처리 중 오류가 발생했습니다."


def ensure_active(job_id: str) -> None:
    with sync_session() as s:
        status = s.execute(text("SELECT status FROM jobs WHERE id = :id"), {"id": job_id}).scalar()
    if status not in ("queued", "running"):
        raise JobStopped(job_id)


class PipelineTask(Task):  # type: ignore[misc]
    abstract = True
    autoretry_for = TRANSIENT_ERRORS
    retry_backoff = 5
    retry_backoff_max = 120
    retry_jitter = True
    max_retries = 3
    acks_late = True

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        files.prune()
        job_id = job_id_from_args(args)
        try:
            if job_id:
                ensure_active(job_id)
            return super().__call__(*args, **kwargs)
        except JobStopped as exc:
            log.info("job_stopped", task=self.name, job_id=job_id)
            raise Ignore() from exc

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        job_id = job_id_from_args(args)
        code, message = user_error(exc)
        log.error(
            "task_failed",
            task=self.name,
            task_id=task_id,
            job_id=job_id,
            code=code,
            error=repr(exc),
            exc_info=exc if code == "internal_error" else None,
        )
        if job_id:
            mark_failed(job_id, code, message)

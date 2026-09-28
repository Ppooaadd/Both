"""Celery application.

Queues:
* ``cpu`` — ingest, rhythm, tonal, merge, finalize, maintenance
* ``ml``  — separation and transcription (GPU workers when available)

Run:
    celery -A pianoforge.worker.celery_app worker -Q cpu -c 4 --prefetch-multiplier 1
    celery -A pianoforge.worker.celery_app worker -Q ml  -c 1 --prefetch-multiplier 1
    celery -A pianoforge.worker.celery_app beat
"""

from __future__ import annotations

from typing import Any

from celery import Celery
from celery.signals import setup_logging, worker_process_init, worker_ready
from kombu import Queue

from pianoforge.config import get_settings
from pianoforge.worker.beat_schedule import BEAT_SCHEDULE

settings = get_settings()

celery_app = Celery(
    "pianoforge",
    broker=settings.broker_url,
    backend=settings.result_backend,
    include=[
        "pianoforge.worker.tasks.ingest",
        "pianoforge.worker.tasks.separate",
        "pianoforge.worker.tasks.analyze",
        "pianoforge.worker.tasks.finalize",
        "pianoforge.worker.tasks.maintenance",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Reliability: a task is acknowledged only after it finishes, and redelivered
    # if the worker process dies (OOM during separation is the common case).
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # Redis redelivers unacked messages after this; must exceed the longest task.
    broker_transport_options={"visibility_timeout": settings.task_time_limit_s * 3},
    result_expires=24 * 3600,
    result_extended=False,
    task_soft_time_limit=settings.task_soft_time_limit_s,
    task_time_limit=settings.task_time_limit_s,
    # ML libraries leak memory across calls; recycle children periodically.
    worker_max_tasks_per_child=50,
    worker_max_memory_per_child=6_000_000,  # KiB
    task_default_queue="cpu",
    task_queues=(Queue("cpu"), Queue("ml")),
    task_routes={
        "pianoforge.separate": {"queue": "ml"},
        "pianoforge.transcribe": {"queue": "ml"},
    },
    task_track_started=True,
    worker_send_task_events=True,
    task_send_sent_event=True,
    beat_schedule=BEAT_SCHEDULE,
)


@setup_logging.connect
def _setup_logging(**_: Any) -> None:
    # Connecting this signal stops Celery from replacing our logging config.
    from pianoforge.logging import configure_logging

    configure_logging()


@worker_process_init.connect
def _init_child(**_: Any) -> None:
    """Each prefork child gets fresh DB/Redis connections and its own model cache."""
    from pianoforge.analysis.registry import reset_registry
    from pianoforge.db.session import dispose_engines_after_fork
    from pianoforge.worker.progress import reset_redis

    dispose_engines_after_fork()
    reset_redis()
    reset_registry()


@worker_ready.connect
def _report_adapters(**_: Any) -> None:
    from pianoforge.analysis.registry import AdapterRegistry
    from pianoforge.logging import get_logger

    get_logger(__name__).info("adapter_availability", adapters=AdapterRegistry(settings).report())

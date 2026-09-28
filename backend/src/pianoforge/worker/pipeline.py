"""Canvas assembly for pipeline jobs.

Full job::

    ingest -> separate -> rhythm -> group(tonal, transcribe) -> merge -> finalize
                                    \\_____ chord ________/

Phase 3 inserts ``arrange -> export`` between ``merge`` and ``finalize``.
"""

from __future__ import annotations

import uuid
from typing import Any

from celery import chain, group
from celery.canvas import Signature

from pianoforge import PIPELINE_VERSION
from pianoforge.worker.celery_app import celery_app

# Tasks are referenced by name so the API process can enqueue pipelines
# without importing the audio/ML stack.
INGEST = "pianoforge.ingest"
SEPARATE = "pianoforge.separate"
RHYTHM = "pianoforge.rhythm"
TONAL = "pianoforge.tonal"
TRANSCRIBE = "pianoforge.transcribe"
MERGE = "pianoforge.merge"
FINALIZE = "pianoforge.finalize"


def _sig(name: str, *args: Any) -> Signature:
    return celery_app.signature(name, args=args)


def initial_context(
    *,
    job_id: uuid.UUID,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    asset_id: uuid.UUID,
    params: dict[str, Any],
) -> dict[str, Any]:
    return {
        "job_id": str(job_id),
        "project_id": str(project_id),
        "user_id": str(user_id),
        "asset_id": str(asset_id),
        "pipeline_version": PIPELINE_VERSION,
        "params": params,
    }


def full_pipeline(ctx: dict[str, Any], root_task_id: str | None = None) -> Signature:
    first = _sig(INGEST, ctx)
    if root_task_id:
        first = first.set(task_id=root_task_id)
    return chain(
        first,
        _sig(SEPARATE),
        _sig(RHYTHM),
        group(_sig(TONAL), _sig(TRANSCRIBE)),
        _sig(MERGE),
        _sig(FINALIZE),
    )


def enqueue_full_pipeline(ctx: dict[str, Any]) -> str:
    """Send the canvas; returns the first task's id (stored on the job for revocation)."""
    root_task_id = str(uuid.uuid4())
    full_pipeline(ctx, root_task_id).apply_async()
    return root_task_id

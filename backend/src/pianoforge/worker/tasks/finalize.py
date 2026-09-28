"""Final stage: link the project to its analysis and mark the job succeeded."""

from __future__ import annotations

import uuid
from typing import Any

from pianoforge.db.models import Project
from pianoforge.db.session import sync_session
from pianoforge.worker import files
from pianoforge.worker.base import PipelineTask
from pianoforge.worker.celery_app import celery_app
from pianoforge.worker.progress import mark_succeeded


@celery_app.task(base=PipelineTask, name="pianoforge.finalize", bind=True)
def finalize(self: PipelineTask, ctx: dict[str, Any]) -> dict[str, Any]:
    analysis_id = ctx.get("analysis_id")
    if analysis_id:
        with sync_session() as s:
            project = s.get(Project, uuid.UUID(ctx["project_id"]))
            if project is not None:
                project.current_analysis_id = uuid.UUID(analysis_id)
    extra = {k: ctx[k] for k in ("analysis_id", "arrangement_id") if ctx.get(k)}
    mark_succeeded(ctx["job_id"], extra)
    files.remove_asset_dir(ctx["asset_id"])
    return {k: v for k, v in ctx.items() if k not in ("stems", "separator_warnings")}

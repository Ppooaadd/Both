"""Stage 6: ScoreIR -> MIDI, MusicXML, PDF, WAV, MP3 in object storage."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete

from pianoforge.arrangement.score_ir import ScoreIR
from pianoforge.audio.buffer import sha256_file
from pianoforge.db.enums import ArrangementStatus, ExportFormat
from pianoforge.db.models import Arrangement, Export
from pianoforge.db.session import sync_session
from pianoforge.export.exporter import Exporter
from pianoforge.export.formats import CONTENT_TYPES
from pianoforge.storage import get_storage
from pianoforge.storage import keys as K
from pianoforge.worker import files
from pianoforge.worker.base import PipelineTask
from pianoforge.worker.celery_app import celery_app
from pianoforge.worker.progress import ProgressReporter
from pianoforge.worker.tasks.arrange import mark_arrangement_failed

_exporter: Exporter | None = None


def get_exporter() -> Exporter:
    global _exporter
    if _exporter is None:
        _exporter = Exporter()
    return _exporter


@celery_app.task(base=PipelineTask, name="pianoforge.export", bind=True)
def export_scores(self: PipelineTask, ctx: dict[str, Any]) -> dict[str, Any]:
    if ctx.get("arrangement_cached"):
        return ctx
    reporter = ProgressReporter(ctx["job_id"], "export", kind=ctx.get("kind", "full"))
    reporter.start()
    arrangement_id = uuid.UUID(ctx["arrangement_id"])
    storage = get_storage()
    try:
        with sync_session() as s:
            row = s.get(Arrangement, arrangement_id)
            assert row is not None and row.score_ir_key
            score_key = row.score_ir_key
        score = ScoreIR.model_validate(storage.get_json_gz(score_key))
        outdir = files.asset_dir(ctx["asset_id"]) / f"export-{arrangement_id}"
        result = get_exporter().export_all(score, outdir, lambda f: reporter(0.85 * f))

        uploaded: list[Export] = []
        for fmt, path in result.files.items():
            key = K.export(arrangement_id, fmt)
            size = storage.upload_file(path, key, CONTENT_TYPES[fmt])
            uploaded.append(
                Export(
                    arrangement_id=arrangement_id,
                    format=ExportFormat(fmt),
                    storage_key=key,
                    size_bytes=size,
                    sha256=sha256_file(path),
                    engine=result.engines.get(fmt, "unknown"),
                )
            )
        with sync_session() as s:
            s.execute(delete(Export).where(Export.arrangement_id == arrangement_id))
            s.add_all(uploaded)
            row = s.get(Arrangement, arrangement_id)
            assert row is not None
            row.status = ArrangementStatus.ready
            row.stats = {
                **row.stats,
                "export_engines": result.engines,
                "export_warnings": result.warnings,
            }
    except Exception:
        mark_arrangement_failed(str(arrangement_id))
        raise

    names = ", ".join(f.upper() for f in result.files)
    pdf_engine = result.engines.get("pdf", "없음")
    reporter.event(f"내보내기 완료: {names} (PDF {pdf_engine}, 오디오 {result.engines['wav']})")
    for w in result.warnings:
        reporter.event(w, level="warn")
    reporter(1.0)
    return ctx

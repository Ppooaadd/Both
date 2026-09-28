"""Stage 2: source separation (``ml`` queue)."""

from __future__ import annotations

from typing import Any

from pianoforge.analysis.registry import get_registry
from pianoforge.analysis.service import run_separation
from pianoforge.audio.buffer import write_flac
from pianoforge.config import get_settings
from pianoforge.storage import ObjectNotFound, get_storage
from pianoforge.storage import keys as K
from pianoforge.worker import files
from pianoforge.worker.base import PipelineTask
from pianoforge.worker.celery_app import celery_app
from pianoforge.worker.progress import ProgressReporter
from pianoforge.worker.tasks.common import load_mix

STEM_LABELS = {
    "vocals": "보컬",
    "drums": "드럼",
    "bass": "베이스",
    "other": "기타 반주",
    "mix": "원음",
}


def _manifest_key(ctx: dict[str, Any]) -> str:
    return f"work/{ctx['asset_id']}/{ctx['pipeline_version']}/stems/manifest.json.gz"


@celery_app.task(base=PipelineTask, name="pianoforge.separate", bind=True)
def separate(self: PipelineTask, ctx: dict[str, Any]) -> dict[str, Any]:
    if ctx.get("cached"):
        return ctx
    storage = get_storage()
    reporter = ProgressReporter(ctx["job_id"], "separate")
    reporter.start()

    # Idempotent: a retried or re-run job reuses stems already in storage.
    try:
        manifest = storage.get_json_gz(_manifest_key(ctx))
    except ObjectNotFound:
        manifest = None
    if manifest is not None:
        reporter.event("이전에 분리한 음원을 재사용합니다")
        reporter(1.0)
        return {**ctx, **manifest}

    mix = load_mix(ctx)
    reporter.event("보컬 · 드럼 · 베이스 · 반주 분리 중")
    outcome = run_separation(mix, get_registry(get_settings()), reporter)
    result = outcome.result
    workdir = files.asset_dir(ctx["asset_id"])

    stems: list[dict[str, Any]] = []
    for kind, buf in result.stems.items():
        if kind == "mix":
            stems.append(
                {
                    "kind": "mix",
                    "engine": result.engine,
                    "rms_db": round(buf.rms_db(), 2),
                    "storage_key": ctx["normalized_key"],
                }
            )
            continue
        key = K.stem(ctx["asset_id"], ctx["pipeline_version"], kind)
        path = write_flac(buf, workdir / f"stem-{kind}.flac")
        storage.upload_file(path, key, "audio/flac")
        stems.append(
            {
                "kind": kind,
                "engine": result.engine,
                "rms_db": round(buf.rms_db(), 2),
                "storage_key": key,
            }
        )

    manifest = {
        "stems": stems,
        "separator_engine": outcome.engine,
        "separator_warnings": [*outcome.warnings, *result.warnings],
    }
    storage.put_json_gz(_manifest_key(ctx), manifest)
    names = ", ".join(STEM_LABELS.get(s["kind"], s["kind"]) for s in stems)
    level = "warn" if outcome.degraded else "info"
    reporter.event(f"분리 완료: {names} ({outcome.engine})", level=level)
    reporter(1.0)
    return {**ctx, **manifest}

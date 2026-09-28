"""Stage 1: validate the upload, deduplicate, enforce quota, decode and normalise."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from pianoforge import PIPELINE_VERSION
from pianoforge.audio import (
    AudioValidationError,
    ProbeResult,
    decode_to_buffer,
    normalize_loudness,
    probe_audio,
    sha256_file,
    write_flac,
)
from pianoforge.config import get_settings
from pianoforge.db.enums import AssetStatus, Plan, UsageKind
from pianoforge.db.models import Analysis, AudioAsset, Project, UsageRecord, User
from pianoforge.db.session import sync_session
from pianoforge.logging import get_logger
from pianoforge.storage import ObjectNotFound, get_storage
from pianoforge.storage import keys as K
from pianoforge.worker import files
from pianoforge.worker.base import PipelineTask
from pianoforge.worker.celery_app import celery_app
from pianoforge.worker.progress import ProgressReporter

log = get_logger(__name__)


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _reject(asset_id: uuid.UUID, exc: AudioValidationError) -> None:
    storage = get_storage()
    with sync_session() as s:
        asset = s.get(AudioAsset, asset_id)
        if asset is None:
            return
        asset.status = AssetStatus.rejected
        asset.reject_reason = f"{exc.code}: {exc.message}"
        key = asset.storage_key
    try:
        storage.delete(key)
    except Exception as e:
        log.warning("reject_delete_failed", key=key, error=repr(e))


@celery_app.task(base=PipelineTask, name="pianoforge.ingest", bind=True)
def ingest(self: PipelineTask, ctx: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    storage = get_storage()
    job_id = ctx["job_id"]
    asset_id = uuid.UUID(ctx["asset_id"])
    reporter = ProgressReporter(job_id, "ingest")
    reporter.start("업로드 파일 검증 중")

    with sync_session() as s:
        asset = s.get(AudioAsset, asset_id)
        user = s.get(User, uuid.UUID(ctx["user_id"]))
        if asset is None or user is None:
            raise AudioValidationError("not_found", "업로드 파일을 찾을 수 없습니다.")
        raw_key = asset.storage_key
        plan = user.plan
        already_valid = asset.status == AssetStatus.valid

    workdir = files.asset_dir(asset_id)
    raw_path = workdir / "raw"
    try:
        files.fetch(storage, raw_key, raw_path)
    except ObjectNotFound as e:
        exc = AudioValidationError("not_uploaded", "업로드가 완료되지 않았습니다.")
        _reject(asset_id, exc)
        raise exc from e
    if raw_path.stat().st_size > settings.upload_max_bytes:
        exc = AudioValidationError("too_large", "파일 크기 제한을 초과했습니다.")
        _reject(asset_id, exc)
        raise exc
    reporter(0.2)

    digest = sha256_file(raw_path)

    # ---- dedupe: same user, same bytes, live asset -> reuse it -------------
    if not already_valid:
        with sync_session() as s:
            existing = s.execute(
                select(AudioAsset).where(
                    AudioAsset.user_id == uuid.UUID(ctx["user_id"]),
                    AudioAsset.sha256 == digest,
                    AudioAsset.id != asset_id,
                    AudioAsset.status == AssetStatus.valid,
                )
            ).scalar_one_or_none()
            if existing is not None:
                dup = s.get(AudioAsset, asset_id)
                assert dup is not None
                dup.status = AssetStatus.purged
                dup.reject_reason = f"duplicate of {existing.id}"
                project = s.get(Project, uuid.UUID(ctx["project_id"]))
                assert project is not None
                project.audio_asset_id = existing.id
                analysis_id = s.execute(
                    select(Analysis.id).where(
                        Analysis.audio_asset_id == existing.id,
                        Analysis.pipeline_version == PIPELINE_VERSION,
                    )
                ).scalar_one_or_none()
                reuse = {
                    "asset_id": str(existing.id),
                    "duration": existing.duration_sec,
                    "sample_rate": settings.target_sample_rate,
                    "normalized_key": K.normalized_audio(existing.id),
                }
        if existing is not None:
            storage.delete(raw_key)
            files.remove_asset_dir(asset_id)
            ctx = {**ctx, **reuse}
            if analysis_id is not None:
                reporter.event("이전에 분석한 동일 파일을 재사용합니다")
                ctx["cached"] = True
                ctx["analysis_id"] = str(analysis_id)
            else:
                reporter.event("동일 파일을 재사용합니다 (분석은 새로 수행)")
            reporter(1.0)
            return ctx

    # ---- validate -----------------------------------------------------------
    max_duration = settings.max_duration_s_pro if plan == Plan.pro else settings.max_duration_s_free
    try:
        info = probe_audio(raw_path, settings, max_duration)
    except AudioValidationError as exc:
        _reject(asset_id, exc)
        raise

    # ---- quota --------------------------------------------------------------
    if plan == Plan.free and not already_valid:
        now = datetime.now(UTC)
        with sync_session() as s:
            used = s.execute(
                select(func.coalesce(func.sum(UsageRecord.amount), 0)).where(
                    UsageRecord.user_id == uuid.UUID(ctx["user_id"]),
                    UsageRecord.kind == UsageKind.analysis_seconds,
                    UsageRecord.created_at >= _month_start(now),
                )
            ).scalar_one()
        if float(used) + info.duration_sec > settings.monthly_analysis_seconds_free:
            quota_err = AudioValidationError(
                "quota_exceeded", "이번 달 무료 분석 시간을 모두 사용했습니다."
            )
            _reject(asset_id, quota_err)
            raise quota_err
    reporter(0.35)

    # ---- decode + normalise -------------------------------------------------
    reporter.event(f"{info.codec} · {info.duration_sec:.1f}초 · {info.sample_rate} Hz 디코딩")
    try:
        decoded = decode_to_buffer(raw_path, workdir / "decoded.wav", settings, max_duration)
    except AudioValidationError as exc:
        _reject(asset_id, exc)
        raise
    reporter(0.7)
    normalized, gain_db = normalize_loudness(decoded, settings.target_lufs)
    norm_path = write_flac(normalized, workdir / "normalized.flac")
    (workdir / "decoded.wav").unlink(missing_ok=True)
    storage.upload_file(norm_path, K.normalized_audio(asset_id), "audio/flac")
    reporter(0.95)

    try:
        _commit_valid(asset_id, digest, info, normalized.duration, ctx["user_id"])
    except IntegrityError as e:
        # A concurrent upload of the same bytes won the unique (user, sha256)
        # index; on retry the dedupe branch above reuses that asset.
        raise self.retry(exc=e, countdown=2, max_retries=2) from e
    reporter.event(f"정규화 완료 (gain {gain_db:+.1f} dB)")
    reporter(1.0)
    return {
        **ctx,
        "duration": normalized.duration,
        "sample_rate": normalized.sample_rate,
        "normalized_key": K.normalized_audio(asset_id),
    }


def _commit_valid(
    asset_id: uuid.UUID, digest: str, info: ProbeResult, duration: float, user_id: str
) -> None:
    settings = get_settings()
    with sync_session() as s:
        asset = s.get(AudioAsset, asset_id)
        assert asset is not None
        first_validation = asset.status != AssetStatus.valid
        asset.sha256 = digest
        asset.duration_sec = duration
        asset.sample_rate = info.sample_rate
        asset.channels = info.channels
        asset.codec = info.codec
        asset.status = AssetStatus.valid
        if asset.purge_after is None:
            asset.purge_after = datetime.now(UTC) + timedelta(days=settings.raw_retention_days)
        if first_validation:
            s.add(
                UsageRecord(
                    user_id=uuid.UUID(user_id),
                    kind=UsageKind.analysis_seconds,
                    amount=Decimal(f"{duration:.3f}"),
                )
            )

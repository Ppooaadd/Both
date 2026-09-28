"""Periodic and on-demand housekeeping."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from celery import shared_task
from sqlalchemy import delete, select, text

from pianoforge.config import get_settings
from pianoforge.db.enums import AssetStatus, JobStatus
from pianoforge.db.models import AudioAsset, Job, JobEvent, Project
from pianoforge.db.session import sync_session
from pianoforge.logging import get_logger
from pianoforge.storage import get_storage
from pianoforge.storage import keys as K
from pianoforge.worker.progress import mark_failed

log = get_logger(__name__)

EVENT_RETENTION_DAYS = 30


def _delete_asset_media(asset: AudioAsset) -> int:
    """Delete raw upload, normalized audio and stems. Analysis JSON is kept."""
    storage = get_storage()
    deleted = 0
    for key in (asset.storage_key, K.normalized_audio(asset.id)):
        storage.delete(key)
        deleted += 1
    deleted += storage.delete_prefix(f"work/{asset.id}/")
    return deleted


@shared_task(name="pianoforge.maintenance.purge_expired_assets")
def purge_expired_assets(batch: int = 200) -> int:
    """Retention policy: remove source audio and stems after ``raw_retention_days``.

    Analyses (JSON) and arrangements stay usable; re-analysis requires re-upload.
    Assets referenced by an active job are skipped until the job ends.
    """
    now = datetime.now(UTC)
    purged = 0
    with sync_session() as s:
        assets = (
            s.execute(
                select(AudioAsset)
                .where(
                    AudioAsset.purge_after < now,
                    AudioAsset.status.in_(
                        [AssetStatus.valid, AssetStatus.pending, AssetStatus.uploaded]
                    ),
                )
                .limit(batch)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        for asset in assets:
            active = s.execute(
                select(Job.id)
                .join(Project, Project.id == Job.project_id)
                .where(
                    Project.audio_asset_id == asset.id,
                    Job.status.in_([JobStatus.queued, JobStatus.running]),
                )
                .limit(1)
            ).first()
            if active:
                continue
            storage = get_storage()
            storage.delete(asset.storage_key)
            storage.delete(K.normalized_audio(asset.id))
            # Stems and intermediate parts; analysis.json.gz stays for existing projects.
            for version_dir in _list_version_dirs(f"work/{asset.id}/"):
                storage.delete_prefix(f"{version_dir}stems/")
                storage.delete_prefix(f"{version_dir}parts/")
            asset.status = AssetStatus.purged
            purged += 1
    log.info("purge_expired_assets", purged=purged)
    return purged


def _list_version_dirs(prefix: str) -> list[str]:
    storage = get_storage()
    client = storage._client
    resp = client.list_objects_v2(Bucket=storage.bucket, Prefix=prefix, Delimiter="/")
    return [p["Prefix"] for p in resp.get("CommonPrefixes", [])]


@shared_task(name="pianoforge.maintenance.reap_stuck_jobs")
def reap_stuck_jobs() -> int:
    """Fail jobs whose worker vanished (no progress for 3x the hard time limit)."""
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.task_time_limit_s * 3)
    with sync_session() as s:
        stuck = (
            s.execute(
                select(Job.id).where(
                    Job.status.in_([JobStatus.queued, JobStatus.running]),
                    Job.created_at < cutoff,
                    text(
                        "NOT EXISTS (SELECT 1 FROM job_events e WHERE e.job_id = jobs.id "
                        "AND e.created_at > :cutoff)"
                    ).bindparams(cutoff=cutoff),
                )
            )
            .scalars()
            .all()
        )
    for job_id in stuck:
        mark_failed(job_id, "timeout", "작업이 응답하지 않아 중단되었습니다. 다시 시도해 주세요.")
    if stuck:
        log.warning("reaped_stuck_jobs", count=len(stuck))
    return len(stuck)


@shared_task(name="pianoforge.maintenance.prune_job_events")
def prune_job_events() -> int:
    cutoff = datetime.now(UTC) - timedelta(days=EVENT_RETENTION_DAYS)
    with sync_session() as s:
        result = s.execute(delete(JobEvent).where(JobEvent.created_at < cutoff))
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


@shared_task(
    name="pianoforge.maintenance.delete_asset",
    autoretry_for=(Exception,),
    max_retries=5,
    retry_backoff=True,
)
def delete_asset(asset_id: str) -> int:
    """Delete an asset's objects once no project references it (after project deletion)."""
    aid = uuid.UUID(asset_id)
    with sync_session() as s:
        asset = s.get(AudioAsset, aid)
        if asset is None:
            return 0
        still_used = s.execute(
            select(Project.id).where(Project.audio_asset_id == aid).limit(1)
        ).first()
        if still_used:
            return 0
        deleted = _delete_asset_media(asset)
        s.delete(asset)
    return deleted


@shared_task(
    name="pianoforge.maintenance.delete_user_data",
    autoretry_for=(Exception,),
    max_retries=5,
    retry_backoff=True,
)
def delete_user_data(user_id: str, asset_ids: list[str]) -> int:
    """Account deletion: remove every object derived from the user's uploads."""
    storage = get_storage()
    deleted = 0
    for prefix in K.user_prefixes(uuid.UUID(user_id)):
        deleted += storage.delete_prefix(prefix)
    for aid in asset_ids:
        storage.delete(K.normalized_audio(uuid.UUID(aid)))
        deleted += storage.delete_prefix(f"work/{aid}/")
    return deleted

"""Periodic maintenance (run by a single ``celery beat`` instance)."""

from __future__ import annotations

from typing import Any

BEAT_SCHEDULE: dict[str, dict[str, Any]] = {
    "purge-expired-assets": {
        "task": "pianoforge.maintenance.purge_expired_assets",
        "schedule": 3600.0,
    },
    "reap-stuck-jobs": {
        "task": "pianoforge.maintenance.reap_stuck_jobs",
        "schedule": 600.0,
    },
    "prune-job-events": {
        "task": "pianoforge.maintenance.prune_job_events",
        "schedule": 24 * 3600.0,
    },
}

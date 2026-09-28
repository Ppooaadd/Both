"""Enumerations persisted as PostgreSQL enum types."""

from __future__ import annotations

import enum


class Plan(enum.StrEnum):
    free = "free"
    pro = "pro"


class AssetStatus(enum.StrEnum):
    pending = "pending"  # upload URL issued, object may not exist yet
    uploaded = "uploaded"  # client confirmed upload, awaiting validation
    valid = "valid"  # passed ffprobe validation
    rejected = "rejected"  # failed validation; object deleted
    purged = "purged"  # retention expired; object deleted


class JobKind(enum.StrEnum):
    full = "full"  # ingest -> separate -> analyze -> arrange -> export
    rearrange = "rearrange"  # arrange -> export from cached analysis
    export = "export"  # single export format


class JobStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    canceled = "canceled"

    @property
    def is_terminal(self) -> bool:
        return self in (JobStatus.succeeded, JobStatus.failed, JobStatus.canceled)


class EventLevel(enum.StrEnum):
    info = "info"
    warn = "warn"
    error = "error"


class KeyMode(enum.StrEnum):
    major = "major"
    minor = "minor"


class StemKind(enum.StrEnum):
    vocals = "vocals"
    drums = "drums"
    bass = "bass"
    other = "other"
    mix = "mix"


class Difficulty(enum.StrEnum):
    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"


class ArrangementStatus(enum.StrEnum):
    pending = "pending"
    ready = "ready"
    failed = "failed"


class ExportFormat(enum.StrEnum):
    midi = "midi"
    musicxml = "musicxml"
    pdf = "pdf"
    wav = "wav"
    mp3 = "mp3"


class UsageKind(enum.StrEnum):
    analysis_seconds = "analysis_seconds"
    rearrange = "rearrange"
    export = "export"

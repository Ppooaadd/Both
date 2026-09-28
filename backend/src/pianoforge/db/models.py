"""ORM models. See docs/architecture.md §4 for the ERD."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pianoforge.db.base import Base, CreatedAt, Timestamps, UUIDPk
from pianoforge.db.enums import (
    ArrangementStatus,
    AssetStatus,
    Difficulty,
    EventLevel,
    ExportFormat,
    JobKind,
    JobStatus,
    KeyMode,
    Plan,
    StemKind,
    UsageKind,
)


def _enum(cls: type, name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class User(UUIDPk, CreatedAt, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    plan: Mapped[Plan] = mapped_column(_enum(Plan, "plan"), default=Plan.free, nullable=False)
    email_verified: Mapped[bool] = mapped_column(default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(UUIDPk, CreatedAt, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True, nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(512))


class AudioAsset(UUIDPk, CreatedAt, Base):
    __tablename__ = "audio_assets"
    __table_args__ = (
        Index(
            "uq_audio_assets_user_sha256_live",
            "user_id",
            "sha256",
            unique=True,
            postgresql_where=text("sha256 IS NOT NULL AND status NOT IN ('purged', 'rejected')"),
        ),
        CheckConstraint("size_bytes >= 0", name="size_nonneg"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    storage_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    duration_sec: Mapped[float | None] = mapped_column(Float)
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    channels: Mapped[int | None] = mapped_column(SmallInteger)
    codec: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[AssetStatus] = mapped_column(
        _enum(AssetStatus, "asset_status"), default=AssetStatus.pending, nullable=False
    )
    reject_reason: Mapped[str | None] = mapped_column(Text)
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class Project(UUIDPk, Timestamps, Base):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_user_created", "user_id", text("created_at DESC")),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    audio_asset_id: Mapped[uuid.UUID] = mapped_column(
        # NO ACTION (checked at statement end) so a user-delete cascade can remove
        # projects and assets together; a lone asset delete is still blocked.
        ForeignKey("audio_assets.id"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    current_analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analyses.id", ondelete="SET NULL", use_alter=True)
    )

    audio_asset: Mapped[AudioAsset] = relationship(lazy="joined")
    current_analysis: Mapped[Analysis | None] = relationship(
        foreign_keys=[current_analysis_id], lazy="selectin"
    )


class Job(UUIDPk, CreatedAt, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_project_created", "project_id", text("created_at DESC")),
        Index(
            "ix_jobs_active",
            "status",
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        CheckConstraint("progress BETWEEN 0 AND 100", name="progress_range"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[JobKind] = mapped_column(_enum(JobKind, "job_kind"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        _enum(JobStatus, "job_status"), default=JobStatus.queued, nullable=False
    )
    stage: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    progress: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    celery_root_id: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship(lazy="joined")


class JobEvent(CreatedAt, Base):
    __tablename__ = "job_events"
    __table_args__ = (Index("ix_job_events_job_id_id", "job_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    level: Mapped[EventLevel] = mapped_column(
        _enum(EventLevel, "event_level"), default=EventLevel.info, nullable=False
    )
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)


class Analysis(UUIDPk, CreatedAt, Base):
    __tablename__ = "analyses"
    __table_args__ = (
        UniqueConstraint("audio_asset_id", "pipeline_version", name="uq_analyses_asset_version"),
        CheckConstraint("key_tonic BETWEEN 0 AND 11", name="key_tonic_range"),
    )

    audio_asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("audio_assets.id", ondelete="CASCADE"), nullable=False
    )
    pipeline_version: Mapped[str] = mapped_column(String(32), nullable=False)
    engine_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    tempo_bpm: Mapped[float] = mapped_column(Float, nullable=False)
    time_signature: Mapped[str] = mapped_column(String(8), default="4/4", nullable=False)
    key_tonic: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    key_mode: Mapped[KeyMode] = mapped_column(_enum(KeyMode, "key_mode"), nullable=False)
    key_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    ir_key: Mapped[str] = mapped_column(Text, nullable=False)

    stems: Mapped[list[Stem]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", lazy="selectin"
    )


class Stem(UUIDPk, Base):
    __tablename__ = "stems"
    __table_args__ = (UniqueConstraint("analysis_id", "kind", name="uq_stems_analysis_kind"),)

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[StemKind] = mapped_column(_enum(StemKind, "stem_kind"), nullable=False)
    engine: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    rms_db: Mapped[float] = mapped_column(Float, nullable=False)

    analysis: Mapped[Analysis] = relationship(back_populates="stems")


class Arrangement(UUIDPk, CreatedAt, Base):
    __tablename__ = "arrangements"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "analysis_id",
            "difficulty",
            "params_hash",
            name="uq_arrangements_project_params",
        ),
        Index("ix_arrangements_project_created", "project_id", text("created_at DESC")),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False
    )
    difficulty: Mapped[Difficulty] = mapped_column(_enum(Difficulty, "difficulty"), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    params_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[ArrangementStatus] = mapped_column(
        _enum(ArrangementStatus, "arrangement_status"),
        default=ArrangementStatus.pending,
        nullable=False,
    )
    score_ir_key: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    exports: Mapped[list[Export]] = relationship(
        back_populates="arrangement", cascade="all, delete-orphan", lazy="selectin"
    )


class Export(UUIDPk, CreatedAt, Base):
    __tablename__ = "exports"
    __table_args__ = (UniqueConstraint("arrangement_id", "format", name="uq_exports_arr_format"),)

    arrangement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("arrangements.id", ondelete="CASCADE"), nullable=False
    )
    format: Mapped[ExportFormat] = mapped_column(
        _enum(ExportFormat, "export_format"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    engine: Mapped[str] = mapped_column(String(64), nullable=False)

    arrangement: Mapped[Arrangement] = relationship(back_populates="exports")


class UsageRecord(CreatedAt, Base):
    __tablename__ = "usage_records"
    __table_args__ = (Index("ix_usage_user_kind_created", "user_id", "kind", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[UsageKind] = mapped_column(_enum(UsageKind, "usage_kind"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)

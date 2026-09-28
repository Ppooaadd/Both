"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-28 22:18:18.406085
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ENUM_TYPES = (
    "plan",
    "asset_status",
    "usage_kind",
    "key_mode",
    "difficulty",
    "arrangement_status",
    "job_kind",
    "job_status",
    "stem_kind",
    "export_format",
    "event_level",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.create_table(
        "users",
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("plan", sa.Enum("free", "pro", name="plan"), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "audio_assets",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("duration_sec", sa.Float(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("channels", sa.SmallInteger(), nullable=True),
        sa.Column("codec", sa.String(length=32), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "uploaded", "valid", "rejected", "purged", name="asset_status"),
            nullable=False,
        ),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_audio_assets_size_nonneg")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_audio_assets_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audio_assets")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_audio_assets_storage_key")),
    )
    op.create_index(
        op.f("ix_audio_assets_purge_after"), "audio_assets", ["purge_after"], unique=False
    )
    op.create_index(op.f("ix_audio_assets_user_id"), "audio_assets", ["user_id"], unique=False)
    op.create_index(
        "uq_audio_assets_user_sha256_live",
        "audio_assets",
        ["user_id", "sha256"],
        unique=True,
        postgresql_where=sa.text("sha256 IS NOT NULL AND status NOT IN ('purged', 'rejected')"),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"], unique=False
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)
    op.create_table(
        "usage_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("analysis_seconds", "rearrange", "export", name="usage_kind"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_usage_records_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_records")),
    )
    op.create_index(
        "ix_usage_user_kind_created",
        "usage_records",
        ["user_id", "kind", "created_at"],
        unique=False,
    )
    op.create_table(
        "analyses",
        sa.Column("audio_asset_id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_version", sa.String(length=32), nullable=False),
        sa.Column("engine_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tempo_bpm", sa.Float(), nullable=False),
        sa.Column("time_signature", sa.String(length=8), nullable=False),
        sa.Column("key_tonic", sa.SmallInteger(), nullable=False),
        sa.Column("key_mode", sa.Enum("major", "minor", name="key_mode"), nullable=False),
        sa.Column("key_confidence", sa.Float(), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ir_key", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("key_tonic BETWEEN 0 AND 11", name=op.f("ck_analyses_key_tonic_range")),
        sa.ForeignKeyConstraint(
            ["audio_asset_id"],
            ["audio_assets.id"],
            name=op.f("fk_analyses_audio_asset_id_audio_assets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analyses")),
        sa.UniqueConstraint("audio_asset_id", "pipeline_version", name="uq_analyses_asset_version"),
    )
    op.create_table(
        "projects",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("audio_asset_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("current_analysis_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["audio_asset_id"],
            ["audio_assets.id"],
            name=op.f("fk_projects_audio_asset_id_audio_assets"),
        ),
        sa.ForeignKeyConstraint(
            ["current_analysis_id"],
            ["analyses.id"],
            name=op.f("fk_projects_current_analysis_id_analyses"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_projects_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
    )
    op.create_index(
        op.f("ix_projects_audio_asset_id"), "projects", ["audio_asset_id"], unique=False
    )
    op.create_index(
        "ix_projects_user_created",
        "projects",
        ["user_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "arrangements",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column(
            "difficulty",
            sa.Enum("beginner", "intermediate", "advanced", name="difficulty"),
            nullable=False,
        ),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("params_hash", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "ready", "failed", name="arrangement_status"),
            nullable=False,
        ),
        sa.Column("score_ir_key", sa.Text(), nullable=True),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_arrangements_analysis_id_analyses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_arrangements_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_arrangements")),
        sa.UniqueConstraint(
            "analysis_id", "difficulty", "params_hash", name="uq_arrangements_analysis_params"
        ),
    )
    op.create_index(
        "ix_arrangements_project_created",
        "arrangements",
        ["project_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "jobs",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Enum("full", "rearrange", "export", name="job_kind"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "succeeded", "failed", "canceled", name="job_status"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.SmallInteger(), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("celery_root_id", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt", sa.SmallInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name=op.f("ck_jobs_progress_range")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_jobs_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index(
        "ix_jobs_active",
        "jobs",
        ["status"],
        unique=False,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_index(
        "ix_jobs_project_created",
        "jobs",
        ["project_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "stems",
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("vocals", "drums", "bass", "other", "mix", name="stem_kind"),
            nullable=False,
        ),
        sa.Column("engine", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("rms_db", sa.Float(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_stems_analysis_id_analyses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stems")),
        sa.UniqueConstraint("analysis_id", "kind", name="uq_stems_analysis_kind"),
    )
    op.create_table(
        "exports",
        sa.Column("arrangement_id", sa.Uuid(), nullable=False),
        sa.Column(
            "format",
            sa.Enum("midi", "musicxml", "pdf", "wav", "mp3", name="export_format"),
            nullable=False,
        ),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("engine", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["arrangement_id"],
            ["arrangements.id"],
            name=op.f("fk_exports_arrangement_id_arrangements"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exports")),
        sa.UniqueConstraint("arrangement_id", "format", name="uq_exports_arr_format"),
    )
    op.create_table(
        "job_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.SmallInteger(), nullable=False),
        sa.Column("level", sa.Enum("info", "warn", "error", name="event_level"), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_job_events_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_events")),
    )
    op.create_index("ix_job_events_job_id_id", "job_events", ["job_id", "id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_job_events_job_id_id", table_name="job_events")
    op.drop_table("job_events")
    op.drop_table("exports")
    op.drop_table("stems")
    op.drop_index("ix_jobs_project_created", table_name="jobs")
    op.drop_index(
        "ix_jobs_active",
        table_name="jobs",
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.drop_table("jobs")
    op.drop_index("ix_arrangements_project_created", table_name="arrangements")
    op.drop_table("arrangements")
    op.drop_index("ix_projects_user_created", table_name="projects")
    op.drop_index(op.f("ix_projects_audio_asset_id"), table_name="projects")
    op.drop_table("projects")
    op.drop_table("analyses")
    op.drop_index("ix_usage_user_kind_created", table_name="usage_records")
    op.drop_table("usage_records")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_family_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index(
        "uq_audio_assets_user_sha256_live",
        table_name="audio_assets",
        postgresql_where=sa.text("sha256 IS NOT NULL AND status NOT IN ('purged', 'rejected')"),
    )
    op.drop_index(op.f("ix_audio_assets_user_id"), table_name="audio_assets")
    op.drop_index(op.f("ix_audio_assets_purge_after"), table_name="audio_assets")
    op.drop_table("audio_assets")
    op.drop_table("users")
    bind = op.get_bind()
    for name in ENUM_TYPES:
        sa.Enum(name=name).drop(bind, checkfirst=True)

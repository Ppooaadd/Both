"""Request/response models. Field names are the public API contract (see docs/api.md)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from pianoforge.arrangement.params import ArrangementParams
from pianoforge.db.enums import AssetStatus, EventLevel, JobKind, JobStatus, Plan

T = TypeVar("T")


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ------------------------------------------------------------------------ auth
class SignupIn(_In):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        classes = sum(bool(re.search(p, v)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^\w\s]"))
        if classes < 2:
            raise ValueError(
                "비밀번호는 영문 대/소문자, 숫자, 특수문자 중 2종류 이상을 포함해야 합니다."
            )
        return v


class LoginIn(_In):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class DeleteAccountIn(_In):
    password: str = Field(min_length=1, max_length=128)


class UserOut(_Out):
    id: uuid.UUID
    email: str
    display_name: str
    plan: Plan
    email_verified: bool
    created_at: datetime


class SessionOut(BaseModel):
    user: UserOut
    csrf_token: str
    access_expires_in: int
    # Also returned for non-browser clients that use the Authorization header.
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret


# ---------------------------------------------------------------------- upload
ALLOWED_EXTENSIONS = (".mp3", ".wav", ".m4a", ".aac", ".mp4")


class UploadCreateIn(_In):
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    mime_type: str = Field(min_length=3, max_length=64)

    @field_validator("filename")
    @classmethod
    def _filename(cls, v: str) -> str:
        name = v.replace("\\", "/").rsplit("/", 1)[-1]
        name = "".join(ch for ch in name if ch.isprintable())
        if not name.lower().endswith(ALLOWED_EXTENSIONS):
            raise ValueError("MP3, WAV, M4A 파일만 업로드할 수 있습니다.")
        return name

    @field_validator("mime_type")
    @classmethod
    def _mime(cls, v: str) -> str:
        return v.lower().split(";", 1)[0].strip()


class UploadCreateOut(BaseModel):
    upload_id: uuid.UUID
    url: str
    fields: dict[str, str]
    expires_in: int
    max_bytes: int


# --------------------------------------------------------------------- project
class ProjectCreateIn(_In):
    upload_id: uuid.UUID
    title: str | None = Field(default=None, max_length=200)
    params: ArrangementParams = Field(default_factory=ArrangementParams)


class ProjectUpdateIn(_In):
    title: str = Field(min_length=1, max_length=200)


class AssetOut(_Out):
    id: uuid.UUID
    original_filename: str
    mime_type: str
    size_bytes: int
    duration_sec: float | None
    sample_rate: int | None
    channels: int | None
    status: AssetStatus
    purge_after: datetime | None


class JobOut(_Out):
    id: uuid.UUID
    project_id: uuid.UUID
    kind: JobKind
    status: JobStatus
    stage: str
    progress: int
    params: dict[str, Any]
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobEventOut(_Out):
    id: int
    stage: str
    progress: int
    level: EventLevel
    message: str
    created_at: datetime


class AnalysisSummaryOut(_Out):
    id: uuid.UUID
    tempo_bpm: float
    time_signature: str
    key_tonic: int
    key_mode: str
    key_confidence: float
    engine_versions: dict[str, Any]
    summary: dict[str, Any]
    created_at: datetime


class ProjectOut(_Out):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    latest_job: JobOut | None = None


class ProjectDetailOut(ProjectOut):
    asset: AssetOut
    analysis: AnalysisSummaryOut | None = None


class ProjectCreatedOut(BaseModel):
    project: ProjectOut
    job: JobOut


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None


# -------------------------------------------------------------------------- ws
class WsTicketIn(_In):
    job_id: uuid.UUID


class WsTicketOut(BaseModel):
    ticket: str
    expires_in: int
    url: str

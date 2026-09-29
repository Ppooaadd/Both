"""Application settings loaded from environment variables (prefix ``PF_``)."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PF_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        enable_decoding=False,  # list fields accept CSV or JSON, parsed in _split_csv
    )

    # --- runtime ---
    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = False

    # --- http ---
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    trusted_hosts: list[str] = Field(default_factory=lambda: ["*"])

    # --- database / redis ---
    database_url: str = "postgresql+psycopg://pianoforge:pianoforge@localhost:5432/pianoforge"
    db_pool_size: int = 10
    db_max_overflow: int = 10
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    # --- object storage ---
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_public_endpoint_url: str | None = None  # host reachable by browsers, if different
    # True when the public URL is a reverse proxy that forwards to s3_endpoint_url with
    # the internal Host header (the Docker stack's Caddy does). URLs are then signed for
    # the internal host and only their origin is rewritten, so the signature stays valid
    # whatever Host the browser or an intermediate forwarder (e.g. Codespaces) sends.
    s3_public_via_proxy: bool = False
    s3_region: str = "us-east-1"
    s3_access_key: SecretStr = SecretStr("minioadmin")
    s3_secret_key: SecretStr = SecretStr("minioadmin")
    s3_bucket: str = "pianoforge"
    s3_force_path_style: bool = True

    # --- auth ---
    jwt_secret: SecretStr = SecretStr("dev-only-change-me-0123456789abcdef")
    jwt_algorithm: str = "HS256"
    access_token_ttl_s: int = 15 * 60
    refresh_token_ttl_s: int = 14 * 24 * 3600
    ws_ticket_ttl_s: int = 30
    cookie_secure: bool = False
    cookie_domain: str | None = None

    # --- upload policy ---
    upload_max_bytes: int = 100 * 1024 * 1024
    upload_url_ttl_s: int = 15 * 60
    download_url_ttl_s: int = 5 * 60
    allowed_mime_types: list[str] = Field(
        default_factory=lambda: [
            "audio/mpeg",
            "audio/mp3",
            "audio/wav",
            "audio/x-wav",
            "audio/wave",
            "audio/mp4",
            "audio/x-m4a",
            "audio/aac",
            "audio/flac",
            "audio/x-flac",
            "audio/ogg",
            "audio/opus",
            "audio/webm",
            "audio/aiff",
            "audio/x-aiff",
            "audio/x-ms-wma",
        ]
    )
    allowed_codecs: list[str] = Field(
        default_factory=lambda: [
            "mp3",
            "pcm_s16le",
            "pcm_s24le",
            "pcm_s32le",
            "pcm_f32le",
            "pcm_s16be",
            "pcm_s24be",
            "pcm_s32be",
            "pcm_f32be",
            "pcm_f64le",
            "pcm_u8",
            "aac",
            "alac",
            "flac",
            "vorbis",
            "opus",
            "wmav1",
            "wmav2",
            "wmapro",
        ]
    )
    allowed_containers: list[str] = Field(
        default_factory=lambda: [
            "mp3",
            "wav",
            "mov",
            "mp4",
            "m4a",
            "3gp",
            "3g2",
            "mj2",
            "flac",
            "ogg",
            "matroska",
            "webm",
            "aiff",
            "asf",
        ]
    )
    max_duration_s_free: float = 10 * 60
    max_duration_s_pro: float = 20 * 60
    raw_retention_days: int = 7

    # --- abuse limits ---
    rate_limit_per_minute: int = 60
    auth_rate_limit_per_minute: int = 10
    max_concurrent_jobs_free: int = 2
    max_concurrent_jobs_pro: int = 5
    monthly_analysis_seconds_free: float = 60 * 60

    # --- audio processing ---
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    target_sample_rate: int = 44_100
    analysis_sample_rate: int = 22_050
    target_lufs: float = -16.0
    work_dir: str = "/tmp/pianoforge"  # noqa: S108 - overridden to a tmpfs in containers

    # --- adapters (comma-separated fallback chains, first available wins) ---
    separator_chain: list[str] = Field(default_factory=lambda: ["demucs", "hpss", "passthrough"])
    transcriber_chain: list[str] = Field(default_factory=lambda: ["basic_pitch", "pyin"])
    beat_tracker_chain: list[str] = Field(
        default_factory=lambda: ["beat_this", "madmom", "librosa", "fixed"]
    )
    key_detector_chain: list[str] = Field(default_factory=lambda: ["krumhansl"])
    chord_recognizer_chain: list[str] = Field(default_factory=lambda: ["hmm", "template"])
    engraver_chain: list[str] = Field(default_factory=lambda: ["verovio", "musescore"])
    renderer_chain: list[str] = Field(default_factory=lambda: ["fluidsynth", "synth"])
    soundfont_path: str | None = None  # defaults to the first SoundFont found on the system
    musescore_path: str | None = None
    demucs_model: str = "htdemucs"
    demucs_device: str = "auto"

    # --- worker ---
    task_soft_time_limit_s: int = 15 * 60
    task_time_limit_s: int = 20 * 60

    @field_validator(
        "cors_origins",
        "trusted_hosts",
        "allowed_mime_types",
        "allowed_codecs",
        "allowed_containers",
        "separator_chain",
        "transcriber_chain",
        "beat_tracker_chain",
        "key_detector_chain",
        "chord_recognizer_chain",
        "engraver_chain",
        "renderer_chain",
        mode="before",
    )
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            text = v.strip()
            if text.startswith("["):
                return json.loads(text)
            return [item.strip() for item in text.split(",") if item.strip()]
        return v

    @field_validator("jwt_secret")
    @classmethod
    def _secret_length(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError("PF_JWT_SECRET must be at least 32 characters")
        return v

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    if settings.is_prod and settings.jwt_secret.get_secret_value().startswith("dev-only"):
        raise RuntimeError("Refusing to start in prod with the development JWT secret")
    return settings

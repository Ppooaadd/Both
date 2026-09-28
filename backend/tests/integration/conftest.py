"""Integration fixtures: real PostgreSQL + Redis, in-process S3 (moto), eager Celery.

Enable with:
    PF_TEST_DATABASE_URL=postgresql+psycopg://user:pw@host:port/db \
    PF_TEST_REDIS_URL=redis://host:port/15 pytest -m integration
"""

from __future__ import annotations

import contextlib
import os
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

if not (os.environ.get("PF_TEST_DATABASE_URL") and os.environ.get("PF_TEST_REDIS_URL")):
    pytest.skip(
        "integration tests need PF_TEST_DATABASE_URL and PF_TEST_REDIS_URL", allow_module_level=True
    )


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session", autouse=True)
def s3_server() -> Iterator[str]:
    from moto.server import ThreadedMotoServer

    port = _free_port()
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=port, verbose=False)
    server.start()
    url = f"http://127.0.0.1:{port}"
    os.environ["PF_S3_ENDPOINT_URL"] = url
    os.environ["PF_S3_ACCESS_KEY"] = "testing"
    os.environ["PF_S3_SECRET_KEY"] = "testing"
    os.environ["PF_S3_BUCKET"] = "pianoforge-test"
    yield url
    server.stop()


@pytest.fixture(scope="session", autouse=True)
def configured(s3_server: str) -> Iterator[None]:
    """Reset cached settings/clients, migrate, create bucket, make Celery eager."""
    from alembic import command
    from alembic.config import Config

    from pianoforge.config import get_settings
    from pianoforge.storage.s3 import get_storage

    get_settings.cache_clear()
    get_storage.cache_clear()

    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    get_storage().ensure_bucket()

    from pianoforge.worker.celery_app import celery_app

    settings = get_settings()
    celery_app.conf.update(
        broker_url=settings.broker_url,
        result_backend=settings.result_backend,
        task_always_eager=True,
        task_eager_propagates=False,
    )
    # Register tasks in this process (workers do this via ``include``).
    import pianoforge.worker.tasks.analyze
    import pianoforge.worker.tasks.finalize
    import pianoforge.worker.tasks.ingest
    import pianoforge.worker.tasks.maintenance
    import pianoforge.worker.tasks.separate  # noqa: F401

    yield


@pytest.fixture(autouse=True)
def clean_db(configured: None) -> Iterator[None]:
    from sqlalchemy import text

    from pianoforge.db.session import get_sync_engine
    from pianoforge.worker.progress import get_redis

    yield
    with get_sync_engine().begin() as conn:
        conn.execute(
            text(
                "TRUNCATE users, refresh_tokens, audio_assets, projects, jobs, job_events, "
                "analyses, stems, arrangements, exports, usage_records RESTART IDENTITY CASCADE"
            )
        )
    get_redis().flushdb()


@pytest.fixture(autouse=True)
def eager_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eager chains re-raise task errors from ``apply_async``; a real broker never does.

    Swallow them here so the API behaves as in production and the test inspects
    the job row, which the task's ``on_failure`` has already marked failed.
    """
    import uuid

    from pianoforge.api.routers import projects
    from pianoforge.worker import pipeline

    def run(ctx: dict[str, object]) -> str:
        root = str(uuid.uuid4())
        with contextlib.suppress(Exception):
            pipeline.full_pipeline(ctx, root).apply_async()
        return root

    monkeypatch.setattr(projects, "enqueue_full_pipeline", run)


@pytest.fixture(scope="session")
def mp3_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from pianoforge.audio.buffer import write_wav
    from pianoforge.audio.decode import encode_mp3
    from pianoforge.config import get_settings
    from tests.synth import render_song

    d = tmp_path_factory.mktemp("audio")
    song = render_song(bpm=100.0, repeats=3)
    wav = write_wav(song.mix, d / "song.wav")
    return encode_mp3(wav, d / "song.mp3", get_settings())

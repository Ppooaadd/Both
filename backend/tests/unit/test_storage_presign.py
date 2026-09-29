"""Presigned URLs behind a reverse proxy keep the internal signature."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from pianoforge.config import Settings
from pianoforge.storage.s3 import Storage


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "s3_endpoint_url": "http://storage:9000",
        "s3_access_key": "k",
        "s3_secret_key": "s",
        "s3_bucket": "pianoforge",
        "jwt_secret": "x" * 40,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_proxy_mode_rewrites_origin_only() -> None:
    public = "https://demo-3000.app.github.dev"
    direct = Storage(_settings(s3_public_endpoint_url=None))
    proxied = Storage(_settings(s3_public_endpoint_url=public, s3_public_via_proxy=True))

    url = proxied.presign_download("a/b.mp3", "song.mp3", "audio/mpeg")
    assert url.startswith(f"{public}/pianoforge/a/b.mp3?")
    # Signed for the internal host: identical query to a direct signature at the same time.
    ref = direct.presign_download("a/b.mp3", "song.mp3", "audio/mpeg")
    assert parse_qs(urlparse(url).query).keys() == parse_qs(urlparse(ref).query).keys()

    post = proxied.presign_upload("uploads/x", "audio/mpeg", 1000)
    assert post.url == f"{public}/pianoforge"


def test_without_proxy_signs_for_public_host() -> None:
    s = Storage(_settings(s3_public_endpoint_url="http://localhost:9000"))
    assert s.presign_download("k", "f.mp3", "audio/mpeg").startswith("http://localhost:9000/")

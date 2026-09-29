"""S3-compatible storage client (MinIO in development).

boto3 is synchronous. The API calls the cheap, network-free presign methods
directly and wraps the rest with ``anyio.to_thread``; workers call everything directly.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from pianoforge.config import Settings, get_settings


@dataclass(frozen=True)
class PresignedPost:
    url: str
    fields: dict[str, str]
    expires_in: int


@dataclass(frozen=True)
class ObjectInfo:
    size: int
    content_type: str | None
    etag: str


class ObjectNotFound(Exception):
    pass


class Storage:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        cfg = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if settings.s3_force_path_style else "auto"},
            retries={"max_attempts": 5, "mode": "standard"},
        )
        common: dict[str, Any] = {
            "region_name": settings.s3_region,
            "aws_access_key_id": settings.s3_access_key.get_secret_value(),
            "aws_secret_access_key": settings.s3_secret_key.get_secret_value(),
            "config": cfg,
        }
        self._client = boto3.client("s3", endpoint_url=settings.s3_endpoint_url, **common)
        # Presigned URLs embed the host in the signature, so they must be signed
        # against the endpoint the browser will actually reach.
        public = settings.s3_public_endpoint_url or settings.s3_endpoint_url
        self._presign_client = (
            self._client
            if public == settings.s3_endpoint_url
            else boto3.client("s3", endpoint_url=public, **common)
        )
        self.bucket = settings.s3_bucket

    # ---- bucket lifecycle -------------------------------------------------
    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self.bucket)

    def ping(self) -> None:
        self._client.head_bucket(Bucket=self.bucket)

    def configure_cors(self, origins: list[str]) -> None:
        """Allow the web app to upload (presigned POST) and fetch (presigned GET) directly."""
        self._client.put_bucket_cors(
            Bucket=self.bucket,
            CORSConfiguration={
                "CORSRules": [
                    {
                        "AllowedOrigins": origins,
                        "AllowedMethods": ["GET", "HEAD", "POST", "PUT"],
                        "AllowedHeaders": ["*"],
                        "ExposeHeaders": ["ETag", "Content-Length", "Content-Range"],
                        "MaxAgeSeconds": 3600,
                    }
                ]
            },
        )

    # ---- presign ----------------------------------------------------------
    def presign_upload(self, key: str, content_type: str, max_bytes: int) -> PresignedPost:
        expires = self._s.upload_url_ttl_s
        post = self._presign_client.generate_presigned_post(
            Bucket=self.bucket,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, max_bytes],
            ],
            ExpiresIn=expires,
        )
        return PresignedPost(url=post["url"], fields=post["fields"], expires_in=expires)

    def presign_download(self, key: str, filename: str, content_type: str) -> str:
        safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ")[:120] or "download"
        return str(
            self._presign_client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                    "ResponseContentDisposition": f'attachment; filename="{safe_name}"',
                    "ResponseContentType": content_type,
                },
                ExpiresIn=self._s.download_url_ttl_s,
            )
        )

    # ---- object ops -------------------------------------------------------
    def head(self, key: str) -> ObjectInfo:
        try:
            r = self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                raise ObjectNotFound(key) from e
            raise
        return ObjectInfo(
            size=int(r["ContentLength"]), content_type=r.get("ContentType"), etag=r["ETag"]
        )

    def exists(self, key: str) -> bool:
        try:
            self.head(key)
        except ObjectNotFound:
            return False
        return True

    def download_file(self, key: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._client.download_file(self.bucket, key, str(dest))
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                raise ObjectNotFound(key) from e
            raise
        return dest

    def upload_file(self, src: Path, key: str, content_type: str) -> int:
        self._client.upload_file(
            str(src), self.bucket, key, ExtraArgs={"ContentType": content_type}
        )
        return src.stat().st_size

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get_bytes(self, key: str) -> bytes:
        try:
            r = self._client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                raise ObjectNotFound(key) from e
            raise
        return bytes(r["Body"].read())

    def put_json_gz(self, key: str, payload: Any) -> str:
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        self.put_bytes(key, gzip.compress(raw, compresslevel=6), "application/gzip")
        return hashlib.sha256(raw).hexdigest()

    def get_json_gz(self, key: str) -> Any:
        return json.loads(gzip.decompress(self.get_bytes(key)))

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)

    def delete_prefix(self, prefix: str) -> int:
        deleted = 0
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objs:
                self._client.delete_objects(Bucket=self.bucket, Delete={"Objects": objs})
                deleted += len(objs)
        return deleted


@lru_cache(maxsize=1)
def get_storage() -> Storage:
    return Storage(get_settings())

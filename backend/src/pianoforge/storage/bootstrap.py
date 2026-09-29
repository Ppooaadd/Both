"""Prepare object storage: create the bucket and its CORS rules. Idempotent.

Run once per deployment (the compose ``storage-init`` service does this):

    python -m pianoforge.storage.bootstrap

Works with any S3-compatible server (RustFS, MinIO, SeaweedFS, AWS S3).
"""

from __future__ import annotations

import sys
import time

from botocore.exceptions import BotoCoreError, ClientError

from pianoforge.config import get_settings
from pianoforge.logging import configure_logging, get_logger
from pianoforge.storage.s3 import get_storage

log = get_logger("pianoforge.storage.bootstrap")


def main(attempts: int = 30, delay_s: float = 2.0) -> int:
    configure_logging()
    settings = get_settings()
    storage = get_storage()
    for attempt in range(1, attempts + 1):
        try:
            storage.ensure_bucket()
            break
        except (BotoCoreError, ClientError) as exc:
            log.info("storage_not_ready", attempt=attempt, error=repr(exc))
            time.sleep(delay_s)
    else:
        log.error("storage_unreachable", endpoint=settings.s3_endpoint_url)
        return 1
    try:
        storage.configure_cors(settings.cors_origins)
    except ClientError as exc:
        # Some servers configure CORS globally instead of per bucket.
        log.warning("bucket_cors_not_set", error=repr(exc))
    log.info("storage_ready", bucket=settings.s3_bucket, cors=settings.cors_origins)
    return 0


if __name__ == "__main__":
    sys.exit(main())

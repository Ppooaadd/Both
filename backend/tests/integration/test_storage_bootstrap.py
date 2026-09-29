"""Storage bootstrap: idempotent bucket creation and CORS for the web origin."""

from __future__ import annotations

from pianoforge.config import get_settings
from pianoforge.storage.bootstrap import main
from pianoforge.storage.s3 import get_storage


def test_bootstrap_is_idempotent_and_sets_cors() -> None:
    assert main(attempts=1, delay_s=0) == 0
    assert main(attempts=1, delay_s=0) == 0

    storage = get_storage()
    storage.ping()
    rules = storage._client.get_bucket_cors(Bucket=storage.bucket)["CORSRules"]
    assert len(rules) == 1
    assert rules[0]["AllowedOrigins"] == get_settings().cors_origins
    assert {"GET", "POST"} <= set(rules[0]["AllowedMethods"])

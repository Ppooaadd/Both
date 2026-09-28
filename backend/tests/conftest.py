"""Test-wide environment. Runs before any ``pianoforge`` module reads settings."""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("PF_ENV", "test")
os.environ.setdefault("PF_LOG_LEVEL", "WARNING")
os.environ.setdefault("PF_WORK_DIR", tempfile.mkdtemp(prefix="pf-test-work-"))
# Fast, dependency-free adapters for tests.
os.environ.setdefault("PF_SEPARATOR_CHAIN", "hpss,passthrough")
os.environ.setdefault("PF_TRANSCRIBER_CHAIN", "pyin")
os.environ.setdefault("PF_BEAT_TRACKER_CHAIN", "librosa,fixed")

if os.environ.get("PF_TEST_DATABASE_URL"):
    os.environ["PF_DATABASE_URL"] = os.environ["PF_TEST_DATABASE_URL"]
if os.environ.get("PF_TEST_REDIS_URL"):
    os.environ["PF_REDIS_URL"] = os.environ["PF_TEST_REDIS_URL"]

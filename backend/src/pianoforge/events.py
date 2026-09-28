"""Job progress events on Redis pub/sub, shared by workers (publish) and the API (subscribe).

Message schema (JSON), discriminated by ``type``:

* ``progress`` — ``{type, job_id, stage, progress, status}``
* ``event``    — ``{type, job_id, id, stage, progress, level, message, created_at}``
* ``status``   — ``{type, job_id, status, stage, progress, error_code?, error_message?,
  analysis_id?}``
"""

from __future__ import annotations

import json
import uuid
from typing import Any

# Overall progress window (percent) owned by each stage. tonal/transcribe run in
# parallel; progress is kept monotonic in SQL with GREATEST().
STAGE_WINDOWS: dict[str, tuple[int, int]] = {
    "queued": (0, 0),
    "ingest": (0, 8),
    "separate": (8, 45),
    "rhythm": (45, 52),
    "tonal": (52, 62),
    "transcribe": (52, 80),
    "merge": (80, 85),
    "arrange": (85, 92),
    "export": (92, 99),
    "done": (100, 100),
}


def channel(job_id: uuid.UUID | str) -> str:
    return f"job:{job_id}"


def encode(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str, separators=(",", ":"))


# Re-arrangement jobs skip analysis, so arrange/export own the whole bar.
REARRANGE_WINDOWS: dict[str, tuple[int, int]] = {
    "queued": (0, 0),
    "arrange": (0, 35),
    "export": (35, 99),
    "done": (100, 100),
}


def overall(stage: str, fraction: float, kind: str = "full") -> int:
    windows = REARRANGE_WINDOWS if kind == "rearrange" else STAGE_WINDOWS
    lo, hi = windows.get(stage, (0, 100))
    f = max(0.0, min(1.0, fraction))
    return round(lo + (hi - lo) * f)

"""Object key layout. Keys never contain user-supplied strings."""

from __future__ import annotations

import uuid


def raw_audio(user_id: uuid.UUID, asset_id: uuid.UUID) -> str:
    return f"raw/{user_id}/{asset_id}"


def normalized_audio(asset_id: uuid.UUID) -> str:
    return f"work/{asset_id}/normalized.flac"


def stem(asset_id: uuid.UUID, pipeline_version: str, kind: str) -> str:
    return f"work/{asset_id}/{pipeline_version}/stems/{kind}.flac"


def analysis_ir(asset_id: uuid.UUID, pipeline_version: str) -> str:
    return f"work/{asset_id}/{pipeline_version}/analysis.json.gz"


def score_ir(arrangement_id: uuid.UUID) -> str:
    return f"arr/{arrangement_id}/score.json.gz"


def export(arrangement_id: uuid.UUID, fmt: str) -> str:
    return f"arr/{arrangement_id}/export/{fmt}"


def user_prefixes(user_id: uuid.UUID) -> list[str]:
    return [f"raw/{user_id}/"]

"""Helpers shared by pipeline tasks."""

from __future__ import annotations

from typing import Any

from pianoforge.audio.buffer import AudioBuffer
from pianoforge.storage import get_storage
from pianoforge.worker import files


def load_mix(ctx: dict[str, Any]) -> AudioBuffer:
    return files.fetch_audio(
        get_storage(), ctx["normalized_key"], ctx["asset_id"], "normalized.flac"
    )


def load_stems(ctx: dict[str, Any]) -> dict[str, AudioBuffer]:
    storage = get_storage()
    out: dict[str, AudioBuffer] = {}
    for stem in ctx.get("stems", []):
        if stem["kind"] == "mix":
            continue
        out[stem["kind"]] = files.fetch_audio(
            storage, stem["storage_key"], ctx["asset_id"], f"stem-{stem['kind']}.flac"
        )
    return out


def part_key(ctx: dict[str, Any], name: str) -> str:
    return f"work/{ctx['asset_id']}/{ctx['pipeline_version']}/parts/{name}.json.gz"

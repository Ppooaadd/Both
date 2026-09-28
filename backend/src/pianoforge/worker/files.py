"""Per-worker scratch space with an S3-backed local cache."""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path

from pianoforge.audio.buffer import AudioBuffer, read_audio
from pianoforge.config import get_settings
from pianoforge.storage.s3 import Storage

PRUNE_EVERY_S = 600.0
MAX_AGE_S = 2 * 3600.0
_last_prune = 0.0


def root() -> Path:
    p = Path(get_settings().work_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def asset_dir(asset_id: uuid.UUID | str) -> Path:
    d = root() / str(asset_id)
    d.mkdir(parents=True, exist_ok=True)
    d.touch()  # mtime marks last use for pruning
    return d


def fetch(storage: Storage, key: str, dest: Path) -> Path:
    """Download ``key`` unless an identical-size local copy already exists."""
    if dest.exists() and dest.stat().st_size == storage.head(key).size:
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    storage.download_file(key, tmp)
    tmp.replace(dest)
    return dest


def fetch_audio(storage: Storage, key: str, asset_id: uuid.UUID | str, name: str) -> AudioBuffer:
    return read_audio(fetch(storage, key, asset_dir(asset_id) / name))


def prune() -> None:
    """Remove cache directories unused for ``MAX_AGE_S`` (throttled)."""
    global _last_prune
    now = time.time()
    if now - _last_prune < PRUNE_EVERY_S:
        return
    _last_prune = now
    for child in root().iterdir():
        try:
            if now - child.stat().st_mtime > MAX_AGE_S:
                shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink()
        except FileNotFoundError:
            continue


def remove_asset_dir(asset_id: uuid.UUID | str) -> None:
    shutil.rmtree(root() / str(asset_id), ignore_errors=True)

"""Every accepted upload format passes validation and decodes (needs ffmpeg)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from pianoforge.audio.decode import decode_to_buffer
from pianoforge.audio.probe import probe_audio
from pianoforge.config import Settings

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

# extension -> extra encoder arguments
FORMATS = {
    "wav": [],
    "mp3": [],
    "m4a": ["-c:a", "aac"],
    "flac": [],
    "ogg": ["-c:a", "libvorbis"],
    "opus": ["-c:a", "libopus"],
    "webm": ["-c:a", "libopus"],
    "aiff": [],
    "wma": ["-c:a", "wmav2"],
}


@pytest.mark.parametrize("ext", sorted(FORMATS))
def test_format_probes_and_decodes(ext: str, tmp_path: Path) -> None:
    src = tmp_path / f"in.{ext}"
    cmd = ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
           "-ac", "2", *FORMATS[ext], str(src)]  # fmt: skip
    if subprocess.run(cmd, capture_output=True, check=False).returncode != 0:
        pytest.skip(f"this ffmpeg build cannot encode {ext}")
    settings = Settings()
    info = probe_audio(src, settings, max_duration_s=600)
    assert info.codec in settings.allowed_codecs
    buf = decode_to_buffer(src, tmp_path / "out.wav", settings, 600)
    assert buf.duration == pytest.approx(2.0, abs=0.1)

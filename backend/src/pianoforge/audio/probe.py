"""Untrusted-input validation with ffprobe.

Every uploaded file is probed before any decoder touches it. The probe runs
with a timeout, without network protocols, and only the first audio stream
is accepted.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pianoforge.config import Settings


class AudioValidationError(Exception):
    """Raised when an upload is not acceptable audio. ``code`` is shown to the user."""

    def __init__(self, code: str, message: str) -> None:
        # Both values in ``args`` so the exception survives Celery serialization.
        super().__init__(code, message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


@dataclass(frozen=True)
class ProbeResult:
    container: str
    codec: str
    duration_sec: float
    sample_rate: int
    channels: int
    bit_rate: int | None


def _run_ffprobe(path: Path, settings: Settings, timeout_s: float) -> dict[str, object]:
    cmd = [
        settings.ffprobe_path,
        "-v", "error",
        "-protocol_whitelist", "file",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]  # fmt: skip
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            cmd, capture_output=True, timeout=timeout_s, check=False
        )
    except subprocess.TimeoutExpired as e:
        raise AudioValidationError("probe_timeout", "파일 분석 시간이 초과되었습니다.") from e
    except FileNotFoundError as e:
        raise RuntimeError(f"ffprobe not found at {settings.ffprobe_path!r}") from e
    if proc.returncode != 0:
        raise AudioValidationError("unreadable", "오디오 파일을 읽을 수 없습니다.")
    try:
        data: dict[str, object] = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise AudioValidationError("unreadable", "오디오 파일을 읽을 수 없습니다.") from e
    return data


def probe_audio(
    path: Path, settings: Settings, max_duration_s: float, timeout_s: float = 30.0
) -> ProbeResult:
    data = _run_ffprobe(path, settings, timeout_s)
    fmt = data.get("format")
    streams = data.get("streams")
    if not isinstance(fmt, dict) or not isinstance(streams, list):
        raise AudioValidationError("unreadable", "오디오 파일을 읽을 수 없습니다.")

    containers = {c.strip() for c in str(fmt.get("format_name", "")).split(",")}
    if not containers & set(settings.allowed_containers):
        raise AudioValidationError(
            "unsupported_container",
            "지원하지 않는 형식입니다. MP3, WAV, M4A 파일만 업로드할 수 있습니다.",
        )

    audio_streams = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"]
    other_streams = [
        s
        for s in streams
        if isinstance(s, dict)
        and s.get("codec_type") != "audio"
        # Cover art in MP3/M4A is a video stream flagged as attached_pic.
        and not (
            s.get("codec_type") == "video" and (s.get("disposition") or {}).get("attached_pic") == 1
        )
    ]
    if not audio_streams:
        raise AudioValidationError("no_audio", "오디오 트랙이 없습니다.")
    if other_streams:
        raise AudioValidationError("has_video", "동영상이 포함된 파일은 지원하지 않습니다.")

    stream = audio_streams[0]
    codec = str(stream.get("codec_name", ""))
    if codec not in settings.allowed_codecs:
        raise AudioValidationError("unsupported_codec", f"지원하지 않는 오디오 코덱입니다: {codec}")

    try:
        duration = float(fmt.get("duration") or stream.get("duration") or 0.0)
        sample_rate = int(stream.get("sample_rate") or 0)
        channels = int(stream.get("channels") or 0)
    except (TypeError, ValueError) as e:
        raise AudioValidationError("unreadable", "오디오 메타데이터가 올바르지 않습니다.") from e

    if duration <= 1.0:
        raise AudioValidationError("too_short", "오디오 길이가 너무 짧습니다 (최소 1초).")
    if duration > max_duration_s:
        minutes = int(max_duration_s // 60)
        raise AudioValidationError("too_long", f"오디오 길이는 최대 {minutes}분까지 지원합니다.")
    if not 8_000 <= sample_rate <= 192_000:
        raise AudioValidationError("bad_sample_rate", "지원하지 않는 샘플레이트입니다.")
    if not 1 <= channels <= 8:
        raise AudioValidationError("bad_channels", "지원하지 않는 채널 구성입니다.")

    bit_rate_raw = fmt.get("bit_rate")
    return ProbeResult(
        container=sorted(containers)[0],
        codec=codec,
        duration_sec=duration,
        sample_rate=sample_rate,
        channels=channels,
        bit_rate=int(bit_rate_raw)
        if isinstance(bit_rate_raw, (str, int)) and str(bit_rate_raw).isdigit()
        else None,
    )

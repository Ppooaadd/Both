"""Decode validated input to float32 PCM with ffmpeg."""

from __future__ import annotations

import subprocess
from pathlib import Path

from pianoforge.audio.buffer import AudioBuffer, read_audio
from pianoforge.audio.probe import AudioValidationError
from pianoforge.config import Settings


def decode_to_buffer(
    src: Path,
    dest_wav: Path,
    settings: Settings,
    max_duration_s: float,
    timeout_s: float = 180.0,
) -> AudioBuffer:
    """Decode the first audio stream to stereo float32 WAV at the target rate.

    ``-t`` caps output length independently of container metadata, which can lie.
    """
    dest_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        settings.ffmpeg_path,
        "-nostdin",
        "-hide_banner",
        "-v", "error",
        "-protocol_whitelist", "file",
        "-threads", "2",
        "-i", str(src),
        "-map", "0:a:0",
        "-vn", "-sn", "-dn",
        "-t", f"{max_duration_s:.3f}",
        "-ac", "2",
        "-ar", str(settings.target_sample_rate),
        "-c:a", "pcm_f32le",
        "-f", "wav",
        "-y", str(dest_wav),
    ]  # fmt: skip
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            cmd, capture_output=True, timeout=timeout_s, check=False
        )
    except subprocess.TimeoutExpired as e:
        raise AudioValidationError("decode_timeout", "오디오 디코딩 시간이 초과되었습니다.") from e
    except FileNotFoundError as e:
        raise RuntimeError(f"ffmpeg not found at {settings.ffmpeg_path!r}") from e
    if proc.returncode != 0 or not dest_wav.exists():
        raise AudioValidationError("decode_failed", "오디오를 디코딩할 수 없습니다.")
    buf = read_audio(dest_wav)
    if buf.frames == 0:
        raise AudioValidationError("decode_failed", "디코딩된 오디오가 비어 있습니다.")
    return buf


def encode_mp3(src_wav: Path, dest_mp3: Path, settings: Settings, bitrate: str = "256k") -> Path:
    cmd = [
        settings.ffmpeg_path, "-nostdin", "-hide_banner", "-v", "error",
        "-i", str(src_wav), "-c:a", "libmp3lame", "-b:a", bitrate, "-y", str(dest_mp3),
    ]  # fmt: skip
    proc = subprocess.run(cmd, capture_output=True, timeout=120, check=False)  # noqa: S603
    if proc.returncode != 0:
        raise RuntimeError(f"mp3 encode failed: {proc.stderr.decode(errors='replace')[-500:]}")
    return dest_mp3

"""Export format metadata. Dependency-free so the API can import it cheaply."""

from __future__ import annotations

CONTENT_TYPES = {
    "midi": "audio/midi",
    "musicxml": "application/vnd.recordare.musicxml+xml",
    "pdf": "application/pdf",
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
}
EXTENSIONS = {"midi": "mid", "musicxml": "musicxml", "pdf": "pdf", "wav": "wav", "mp3": "mp3"}

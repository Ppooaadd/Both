"""Last-resort separator: no separation; every role reads the full mix."""

from __future__ import annotations

from typing import ClassVar

from pianoforge.analysis.interfaces import ProgressFn, SeparationResult, SourceSeparator, _noop
from pianoforge.audio.buffer import AudioBuffer


class PassthroughSeparator(SourceSeparator):
    name: ClassVar[str] = "passthrough"
    version: ClassVar[str] = "1"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def separate(self, audio: AudioBuffer, progress: ProgressFn = _noop) -> SeparationResult:
        progress(1.0)
        return SeparationResult(
            stems={"mix": audio},
            engine=self.engine_id,
            warnings=["separator: no separation; analysis uses the full mix"],
        )

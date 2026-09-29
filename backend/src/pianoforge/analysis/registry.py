"""Adapter registry with configurable fallback chains.

Two kinds of fallback:
* **static** — ``is_available()`` is false (package not installed): skipped at resolve time.
* **runtime** — the adapter raised (OOM, model download failure): the next one is tried.

The engine that actually produced a result is returned so it can be recorded.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from pianoforge.analysis.interfaces import (
    Adapter,
    BeatTracker,
    ChordRecognizer,
    Interrupted,
    KeyDetector,
    NoteTranscriber,
    SourceSeparator,
)
from pianoforge.config import Settings
from pianoforge.logging import get_logger

log = get_logger(__name__)

A = TypeVar("A", bound=Adapter)
R = TypeVar("R")


class NoAdapterAvailable(RuntimeError):
    pass


# Exceptions that abort the whole stage instead of triggering engine fallback.
# The worker registers Celery's soft time limit here at import time.
PROPAGATE: list[type[BaseException]] = [Interrupted]


def register_propagating(*exc_types: type[BaseException]) -> None:
    for t in exc_types:
        if t not in PROPAGATE:
            PROPAGATE.append(t)


@dataclass
class FallbackOutcome(Generic[R]):
    result: R
    engine: str
    adapter_cls: type[Adapter]
    degraded: bool  # True when the first configured adapter did not produce the result
    warnings: list[str] = field(default_factory=list)


class AdapterChain(Generic[A]):
    def __init__(self, role: str, candidates: Sequence[type[A]], configured: Sequence[str]) -> None:
        self.role = role
        self.configured = list(configured)
        by_name = {c.name: c for c in candidates}
        unknown = [n for n in configured if n not in by_name]
        if unknown:
            raise ValueError(f"unknown {role} adapter(s): {unknown}; known: {sorted(by_name)}")
        self._classes = [by_name[n] for n in configured]
        self._instances: dict[str, A] = {}

    def available(self) -> list[type[A]]:
        return [c for c in self._classes if c.is_available()]

    def _instance(self, cls: type[A]) -> A:
        inst = self._instances.get(cls.name)
        if inst is None:
            inst = cls()
            self._instances[cls.name] = inst
        return inst

    def primary(self) -> A:
        avail = self.available()
        if not avail:
            raise NoAdapterAvailable(f"no available {self.role} adapter in {self.configured}")
        return self._instance(avail[0])

    def run(self, fn: Callable[[A], R]) -> FallbackOutcome[R]:
        warnings: list[str] = []
        first = self.configured[0] if self.configured else None
        for cls in self._classes:
            if not cls.is_available():
                warnings.append(f"{self.role}: {cls.name} not installed")
                continue
            adapter = self._instance(cls)
            try:
                result = fn(adapter)
            except tuple(PROPAGATE):
                raise
            except Exception as exc:  # any engine failure triggers fallback
                log.warning("adapter_failed", role=self.role, adapter=cls.name, error=repr(exc))
                warnings.append(f"{self.role}: {cls.name} failed ({type(exc).__name__})")
                # Drop the instance so a broken model is not reused.
                self._instances.pop(cls.name, None)
                continue
            return FallbackOutcome(
                result=result,
                engine=adapter.engine_id,
                adapter_cls=cls,
                degraded=cls.name != first,
                warnings=warnings,
            )
        raise NoAdapterAvailable(f"all {self.role} adapters failed: {warnings}")


class AdapterRegistry:
    """Builds one chain per role from settings. One registry per worker process."""

    def __init__(self, settings: Settings) -> None:
        from pianoforge.analysis.adapters import (
            BEAT_TRACKERS,
            CHORD_RECOGNIZERS,
            KEY_DETECTORS,
            SEPARATORS,
            TRANSCRIBERS,
            VOCAL_TRANSCRIBERS,
        )

        self.separator: AdapterChain[SourceSeparator] = AdapterChain(
            "separator", SEPARATORS, settings.separator_chain
        )
        self.transcriber: AdapterChain[NoteTranscriber] = AdapterChain(
            "transcriber", TRANSCRIBERS, settings.transcriber_chain
        )
        self.vocal_transcriber: AdapterChain[NoteTranscriber] = AdapterChain(
            "vocal_transcriber", VOCAL_TRANSCRIBERS, settings.vocal_transcriber_chain
        )
        self.beat_tracker: AdapterChain[BeatTracker] = AdapterChain(
            "beat_tracker", BEAT_TRACKERS, settings.beat_tracker_chain
        )
        self.key_detector: AdapterChain[KeyDetector] = AdapterChain(
            "key_detector", KEY_DETECTORS, settings.key_detector_chain
        )
        self.chord_recognizer: AdapterChain[ChordRecognizer] = AdapterChain(
            "chord_recognizer", CHORD_RECOGNIZERS, settings.chord_recognizer_chain
        )

    def report(self) -> dict[str, list[dict[str, object]]]:
        """Availability matrix for /readyz and startup logs."""
        out: dict[str, list[dict[str, object]]] = {}
        for chain in (
            self.separator,
            self.vocal_transcriber,
            self.transcriber,
            self.beat_tracker,
            self.key_detector,
            self.chord_recognizer,
        ):
            out[chain.role] = [
                {"name": c.name, "available": c.is_available()} for c in chain._classes
            ]
        return out


_registry: AdapterRegistry | None = None


def get_registry(settings: Settings) -> AdapterRegistry:
    global _registry
    if _registry is None:
        _registry = AdapterRegistry(settings)
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = None

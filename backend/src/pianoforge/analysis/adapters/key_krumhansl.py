"""Key detection by correlating a duration-weighted chroma profile with the
Krumhansl-Kessler probe-tone profiles (24 candidate keys)."""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from pianoforge.analysis.adapters._tonal import F64, beat_chroma
from pianoforge.analysis.interfaces import KeyDetector, TonalInput
from pianoforge.analysis.ir import PITCH_CLASS_NAMES, KeyInfo

KK_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
BASS_WEIGHT = 0.5
SILENCE_DB = -50.0


def key_scores(profile: F64) -> dict[tuple[int, str], float]:
    scores: dict[tuple[int, str], float] = {}
    for tonic in range(12):
        for mode, ref in (("major", KK_MAJOR), ("minor", KK_MINOR)):
            rotated = np.roll(ref, tonic)
            scores[(tonic, mode)] = float(np.corrcoef(profile, rotated)[0, 1])
    return scores


class KrumhanslKeyDetector(KeyDetector):
    name: ClassVar[str] = "krumhansl"
    version: ClassVar[str] = "1"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def detect(self, data: TonalInput) -> KeyInfo:
        bc = beat_chroma(data)
        weights = np.diff(bc.bounds) * (bc.energy_db > SILENCE_DB)
        if not np.any(weights > 0):
            return KeyInfo(tonic=0, mode="major", confidence=0.0)
        profile = bc.chroma @ weights
        if bc.bass is not None:
            profile = profile + BASS_WEIGHT * (bc.bass @ weights)
        if not np.any(profile > 0) or np.allclose(profile, profile[0]):
            return KeyInfo(tonic=0, mode="major", confidence=0.0)

        scores = key_scores(profile)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        (tonic, mode), best = ranked[0]
        second = ranked[1][1]
        confidence = float(np.clip(0.5 * max(best, 0.0) + 2.5 * (best - second), 0.0, 1.0))
        candidates = {f"{PITCH_CLASS_NAMES[t]}:{m}": round(s, 4) for (t, m), s in ranked[:5]}
        return KeyInfo(
            tonic=tonic,
            mode="major" if mode == "major" else "minor",
            confidence=confidence,
            candidates=candidates,
        )

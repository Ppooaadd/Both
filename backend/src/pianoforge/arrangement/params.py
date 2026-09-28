"""User-adjustable arrangement parameters (validated at the API boundary).

The arrangement engine (Phase 3) consumes this model; the API stores it in
``jobs.params`` / ``arrangements.params`` and hashes it for deduplication.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pianoforge.db.enums import Difficulty

QuantizeGrid = Literal["auto", "1/4", "1/8", "1/16", "1/8t"]
LeftHandPattern = Literal["auto", "root", "block", "alberti", "arpeggio", "stride"]
MelodySource = Literal["auto", "vocals", "other"]


class ArrangementParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    difficulty: Difficulty = Difficulty.intermediate
    transpose: int = Field(default=0, ge=-6, le=6, description="Semitones")
    simplify_key: bool = Field(
        default=False, description="Beginner: transpose to the nearest of C/G/F/Am/Dm"
    )
    tempo_scale: float = Field(default=1.0, ge=0.5, le=1.5)
    melody_source: MelodySource = "auto"
    left_hand_pattern: LeftHandPattern = "auto"
    quantize_grid: QuantizeGrid = "auto"
    density: float = Field(default=0.5, ge=0.0, le=1.0)
    range_low: int = Field(default=36, ge=21, le=108, description="MIDI note, lowest allowed")
    range_high: int = Field(default=96, ge=21, le=108, description="MIDI note, highest allowed")
    include_intro_outro: bool = True

    @model_validator(mode="after")
    def _range(self) -> ArrangementParams:
        if self.range_high - self.range_low < 24:
            raise ValueError("range_high must be at least two octaves above range_low")
        return self

    def canonical_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

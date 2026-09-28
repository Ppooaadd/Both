"""Export orchestration: MIDI, MusicXML, PDF (engraver chain) and audio (renderer chain)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pianoforge.analysis.registry import AdapterChain
from pianoforge.arrangement.score_ir import ScoreIR
from pianoforge.audio.decode import encode_mp3
from pianoforge.config import get_settings
from pianoforge.export.engrave import ENGRAVERS, ScoreEngraver
from pianoforge.export.midi import write_midi
from pianoforge.export.musicxml import write_musicxml
from pianoforge.export.render_audio import RENDERERS, AudioRenderer


@dataclass
class ExportResult:
    files: dict[str, Path]
    engines: dict[str, str]
    warnings: list[str] = field(default_factory=list)


class Exporter:
    def __init__(self) -> None:
        s = get_settings()
        self.engravers: AdapterChain[ScoreEngraver] = AdapterChain(
            "engraver", ENGRAVERS, s.engraver_chain
        )
        self.renderers: AdapterChain[AudioRenderer] = AdapterChain(
            "renderer", RENDERERS, s.renderer_chain
        )

    def export_all(self, score: ScoreIR, outdir: Path, progress: object = None) -> ExportResult:
        """Write every format into ``outdir``. PDF/audio failures degrade, never abort."""
        step = progress if callable(progress) else (lambda _f: None)
        outdir.mkdir(parents=True, exist_ok=True)
        files: dict[str, Path] = {}
        engines: dict[str, str] = {"midi": "mido", "musicxml": "music21"}
        warnings: list[str] = []

        files["midi"] = write_midi(score, outdir / "score.mid")
        step(0.1)
        files["musicxml"] = write_musicxml(score, outdir / "score.musicxml")
        step(0.3)

        try:
            out = self.engravers.run(lambda a: a.engrave(files["musicxml"], outdir / "score.pdf"))
            files["pdf"] = out.result
            engines["pdf"] = out.engine
            warnings.extend(out.warnings)
        except Exception as exc:
            warnings.append(f"pdf: unavailable ({type(exc).__name__}); download MusicXML instead")
        step(0.6)

        out_audio = self.renderers.run(
            lambda a: a.render(score, files["midi"], outdir / "piano.wav")
        )
        files["wav"] = out_audio.result
        engines["wav"] = engines["mp3"] = out_audio.engine
        warnings.extend(out_audio.warnings)
        step(0.9)
        files["mp3"] = encode_mp3(files["wav"], outdir / "piano.mp3", get_settings())
        step(1.0)
        return ExportResult(files=files, engines=engines, warnings=warnings)

"""PDF engraving adapters: MusicXML -> PDF.

* ``verovio``   Verovio renders SVG pages; cairosvg converts each page to PDF; pypdf merges.
* ``musescore`` MuseScore CLI, when installed (headless via QT_QPA_PLATFORM=offscreen).
"""

from __future__ import annotations

import importlib.util
import io
import os
import re
import shutil
import subprocess
from abc import abstractmethod
from functools import lru_cache
from pathlib import Path
from typing import ClassVar

from pianoforge.analysis.interfaces import Adapter
from pianoforge.config import get_settings

A4_WIDTH = 2100  # Verovio units: 1/10 mm
A4_HEIGHT = 2970
# cairosvg sizes are CSS pixels (96 dpi): A4 = 210 x 297 mm = 794 x 1123 px = 595 x 842 pt.
A4_PX = (794, 1123)


class ScoreEngraver(Adapter):
    role: ClassVar[str] = "engraver"

    @abstractmethod
    def engrave(self, musicxml: Path, pdf: Path) -> Path: ...


@lru_cache(maxsize=1)
def _cairosvg_ok() -> bool:
    # cairosvg imports libcairo at import time; a missing system library raises OSError.
    try:
        import cairosvg  # noqa: F401
    except Exception:
        return False
    return True


class VerovioEngraver(ScoreEngraver):
    name: ClassVar[str] = "verovio"
    version: ClassVar[str] = "4"

    @classmethod
    def is_available(cls) -> bool:
        return (
            importlib.util.find_spec("verovio") is not None
            and importlib.util.find_spec("pypdf") is not None
            and _cairosvg_ok()
        )

    def engrave(self, musicxml: Path, pdf: Path) -> Path:
        import cairosvg
        import verovio
        from pypdf import PdfReader, PdfWriter

        # Verovio initialises its font resources per thread; outside the importing
        # thread (thread/gevent pools, eager tasks) they must be set explicitly.
        tk = verovio.toolkit(False)
        tk.setResourcePath(str(Path(verovio.__file__).parent / "data"))
        tk.setOptions(
            {
                "pageWidth": A4_WIDTH,
                "pageHeight": A4_HEIGHT,
                "pageMarginTop": 80,
                "pageMarginBottom": 80,
                "pageMarginLeft": 80,
                "pageMarginRight": 80,
                "scale": 45,
                "adjustPageHeight": False,
                "breaks": "auto",
                "header": "auto",
                "footer": "encoded",
                "svgViewBox": True,
            }
        )
        if not tk.loadFile(str(musicxml)):
            raise RuntimeError(f"verovio could not load the MusicXML: {tk.getLog()[-500:]}")
        writer = PdfWriter()
        for page in range(1, tk.getPageCount() + 1):
            svg = _cjk_fonts(tk.renderToSVG(page))
            page_pdf = cairosvg.svg2pdf(
                bytestring=svg.encode("utf-8"),
                output_width=A4_PX[0],
                output_height=A4_PX[1],
            )
            for p in PdfReader(io.BytesIO(page_pdf)).pages:
                writer.add_page(p)
        if len(writer.pages) == 0:
            raise RuntimeError("verovio produced no pages")
        pdf.parent.mkdir(parents=True, exist_ok=True)
        with pdf.open("wb") as f:
            writer.write(f)
        return pdf


HANGUL_OR_CJK = re.compile(r"[\u1100-\u11ff\u3040-\u30ff\u3130-\u318f\u4e00-\u9fff\uac00-\ud7a3]")
CJK_FONT = "NanumMyeongjo"


@lru_cache(maxsize=1)
def _cjk_font_installed() -> bool:
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv
            ["fc-list", f":family={CJK_FONT}"],  # noqa: S607 - fontconfig tool on PATH
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool(out.stdout.strip())


def _cjk_fonts(svg: str) -> str:
    """Point Verovio's text (title, lyrics, directions) at a Korean-capable font.

    cairosvg does not fall back per glyph, so Hangul in a Times face renders as
    boxes. Nanum Myeongjo is a serif with Latin glyphs, so the page stays
    typographically consistent. Music glyphs use their own SMuFL font and are
    unaffected.
    """
    if not HANGUL_OR_CJK.search(svg) or not _cjk_font_installed():
        return svg
    return svg.replace("Times,serif", CJK_FONT).replace("Times, serif", CJK_FONT)


def _musescore_bin() -> str | None:
    configured = get_settings().musescore_path
    if configured and shutil.which(configured):
        return shutil.which(configured)
    for name in ("mscore", "musescore", "mscore4portable", "musescore4", "mscore3"):
        found = shutil.which(name)
        if found:
            return found
    return None


class MuseScoreEngraver(ScoreEngraver):
    name: ClassVar[str] = "musescore"
    version: ClassVar[str] = "cli"

    @classmethod
    def is_available(cls) -> bool:
        return _musescore_bin() is not None

    def engrave(self, musicxml: Path, pdf: Path) -> Path:
        binary = _musescore_bin()
        assert binary is not None
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
        proc = subprocess.run(  # noqa: S603 - fixed argv
            [binary, "-o", str(pdf), str(musicxml)],
            capture_output=True,
            timeout=180,
            env=env,
            check=False,
        )
        if proc.returncode != 0 or not pdf.exists():
            raise RuntimeError(f"musescore failed: {proc.stderr.decode(errors='replace')[-300:]}")
        return pdf


ENGRAVERS: list[type[ScoreEngraver]] = [VerovioEngraver, MuseScoreEngraver]

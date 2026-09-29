"""Download the vocadito dataset (solo singing with note annotations, CC BY 4.0).

    python -m bench.fetch_vocadito

Citation: Bittner, R. M., Pasalo, K., Bosch, J. J., Meseguer-Brocal, G. &
Rubinstein, D. (2021). vocadito: A dataset of solo vocals with f0, note, and
lyric annotations. https://doi.org/10.5281/zenodo.5578807
"""

from __future__ import annotations

import shutil
import urllib.request
import zipfile

from bench.songs import VOCADITO

URL = "https://zenodo.org/api/records/5578807/files/vocadito.zip/content"


def main() -> None:
    if (VOCADITO / "Audio").is_dir():
        print(f"already present: {VOCADITO}")
        return
    VOCADITO.mkdir(parents=True, exist_ok=True)
    archive = VOCADITO / "vocadito.zip"
    print(f"downloading {URL}")
    urllib.request.urlretrieve(URL, archive)
    with zipfile.ZipFile(archive) as z:
        z.extractall(VOCADITO)
    shutil.rmtree(VOCADITO / "__MACOSX", ignore_errors=True)
    archive.unlink()
    print(f"extracted to {VOCADITO}")


if __name__ == "__main__":
    main()

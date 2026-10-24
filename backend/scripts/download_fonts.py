"""Download the bundled open-source fonts (SIL Open Font License) from the google/fonts repo.

Usage (from the backend folder):  python scripts/download_fonts.py
Fonts are saved to app/fonts/, licences to app/fonts/licenses/. Already-present files are skipped.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.fonts import BUNDLED_FONTS, FONTS_DIR  # noqa: E402

BASE = "https://raw.githubusercontent.com/google/fonts/main/"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - fixed https host
        return response.read()


def main() -> int:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    licenses = FONTS_DIR / "licenses"
    licenses.mkdir(exist_ok=True)
    failures = 0
    for font_id, family, _, directory, candidates in BUNDLED_FONTS:
        if any((FONTS_DIR / c).is_file() for c in candidates):
            print(f"[skip] {family} already present")
            continue
        for candidate in candidates:
            url = BASE + directory + "/" + urllib.parse.quote(candidate)
            try:
                data = fetch(url)
            except urllib.error.HTTPError:
                continue
            (FONTS_DIR / candidate).write_bytes(data)
            print(f"[ok]   {family} -> {candidate} ({len(data) // 1024} KB)")
            try:
                (licenses / f"{font_id}-OFL.txt").write_bytes(fetch(BASE + directory + "/OFL.txt"))
            except urllib.error.URLError:
                print(f"[warn] licence for {family} not found")
            break
        else:
            failures += 1
            print(f"[fail] {family}: none of {candidates} found")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

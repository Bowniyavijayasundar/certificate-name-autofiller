"""Font registry: bundled open-source fonts, well-known system fonts and user uploads."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import ImageFont

from .renderer import FontSpec

FONTS_DIR = Path(__file__).resolve().parent / "fonts"

# id, display family, category, google/fonts directory, candidate file names (first found wins).
BUNDLED_FONTS: list[tuple[str, str, str, str, list[str]]] = [
    ("great-vibes", "Great Vibes", "script", "ofl/greatvibes", ["GreatVibes-Regular.ttf"]),
    ("pinyon-script", "Pinyon Script", "script", "ofl/pinyonscript", ["PinyonScript-Regular.ttf"]),
    ("alex-brush", "Alex Brush", "script", "ofl/alexbrush", ["AlexBrush-Regular.ttf"]),
    ("allura", "Allura", "script", "ofl/allura", ["Allura-Regular.ttf"]),
    ("dancing-script", "Dancing Script", "script", "ofl/dancingscript", ["DancingScript[wght].ttf"]),
    ("playfair-display", "Playfair Display", "serif", "ofl/playfairdisplay", ["PlayfairDisplay[wght].ttf"]),
    ("cinzel", "Cinzel", "serif", "ofl/cinzel", ["Cinzel[wght].ttf"]),
    ("eb-garamond", "EB Garamond", "serif", "ofl/ebgaramond", ["EBGaramond[wght].ttf"]),
    ("lora", "Lora", "serif", "ofl/lora", ["Lora[wght].ttf"]),
    ("libre-baskerville", "Libre Baskerville", "serif", "ofl/librebaskerville",
     ["LibreBaskerville[wght].ttf", "LibreBaskerville-Bold.ttf"]),
    ("montserrat", "Montserrat", "sans-serif", "ofl/montserrat", ["Montserrat[wght].ttf"]),
    ("open-sans", "Open Sans", "sans-serif", "ofl/opensans", ["OpenSans[wdth,wght].ttf"]),
    ("noto-sans", "Noto Sans", "sans-serif", "ofl/notosans", ["NotoSans[wdth,wght].ttf"]),
]

# Named instances of variable fonts that are offered in the UI.
VARIATION_WHITELIST = ("Regular", "Medium", "SemiBold", "Bold")

# Common fonts already installed on the machine (not redistributed, just used if present).
SYSTEM_FONTS: list[tuple[str, str, list[str]]] = [
    ("Times New Roman", "serif", ["times.ttf", "Times New Roman.ttf"]),
    ("Times New Roman Bold", "serif", ["timesbd.ttf", "Times New Roman Bold.ttf"]),
    ("Times New Roman Italic", "serif", ["timesi.ttf", "Times New Roman Italic.ttf"]),
    ("Times New Roman Bold Italic", "serif", ["timesbi.ttf", "Times New Roman Bold Italic.ttf"]),
    ("Georgia", "serif", ["georgia.ttf", "Georgia.ttf"]),
    ("Georgia Bold", "serif", ["georgiab.ttf", "Georgia Bold.ttf"]),
    ("Garamond", "serif", ["GARA.TTF"]),
    ("Book Antiqua", "serif", ["BKANT.TTF"]),
    ("Palatino Linotype", "serif", ["pala.ttf"]),
    ("Palatino Linotype Bold", "serif", ["palab.ttf"]),
    ("Cambria", "serif", ["cambria.ttc"]),
    ("Cambria Bold", "serif", ["cambriab.ttf"]),
    ("Constantia", "serif", ["constan.ttf"]),
    ("Arial", "sans-serif", ["arial.ttf", "Arial.ttf"]),
    ("Arial Bold", "sans-serif", ["arialbd.ttf", "Arial Bold.ttf"]),
    ("Calibri", "sans-serif", ["calibri.ttf"]),
    ("Calibri Bold", "sans-serif", ["calibrib.ttf"]),
    ("Segoe UI", "sans-serif", ["segoeui.ttf"]),
    ("Segoe UI Bold", "sans-serif", ["segoeuib.ttf"]),
    ("Verdana", "sans-serif", ["verdana.ttf", "Verdana.ttf"]),
    ("Nirmala UI (Indic scripts)", "sans-serif", ["Nirmala.ttf", "Nirmala.ttc"]),
    ("Monotype Corsiva", "script", ["MTCORSVA.TTF"]),
    ("Edwardian Script ITC", "script", ["ITCEDSCR.TTF"]),
    ("Lucida Calligraphy", "script", ["LCALLIG.TTF"]),
    ("Brush Script MT", "script", ["BRUSHSCI.TTF"]),
    ("Old English Text MT", "display", ["OLDENGL.TTF"]),
    ("DejaVu Sans", "sans-serif", ["DejaVuSans.ttf"]),
    ("DejaVu Serif", "serif", ["DejaVuSerif.ttf"]),
    ("Liberation Serif", "serif", ["LiberationSerif-Regular.ttf"]),
    ("Liberation Sans", "sans-serif", ["LiberationSans-Regular.ttf"]),
]

DEFAULT_FONT_IDS = ("playfair-display:Bold", "playfair-display:Regular", "system:times-new-roman-bold")


@dataclass(frozen=True)
class FontEntry:
    id: str
    name: str
    category: str
    source: str               # bundled | system | uploaded | builtin
    path: Optional[Path]
    index: int = 0
    variation: Optional[str] = None

    @property
    def spec(self) -> FontSpec:
        return FontSpec(str(self.path) if self.path else None, self.index, self.variation)

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "source": self.source,
            "variation": self.variation,
            "has_file": self.path is not None,
        }


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in text.lower()).strip("-")


def _system_font_dirs() -> list[Path]:
    dirs: list[Path] = []
    if sys.platform.startswith("win"):
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        dirs.append(windir / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    elif sys.platform == "darwin":
        dirs += [Path("/Library/Fonts"), Path("/System/Library/Fonts"), Path.home() / "Library/Fonts"]
    else:
        dirs += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts"]
    return [d for d in dirs if d.is_dir()]


def _index_system_files() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for directory in _system_font_dirs():
        try:
            iterator = directory.rglob("*") if not sys.platform.startswith("win") else directory.iterdir()
            for path in iterator:
                if path.suffix.lower() in (".ttf", ".otf", ".ttc"):
                    found.setdefault(path.name.lower(), path)
        except OSError:
            continue
    return found


def _variable_instances(path: Path) -> list[str]:
    try:
        font = ImageFont.truetype(str(path), size=20)
        names = [n.decode() if isinstance(n, bytes) else str(n) for n in font.get_variation_names()]
    except (OSError, ValueError, AttributeError):
        return []
    return [n for n in VARIATION_WHITELIST if n in names]


def validate_font_file(path: Path) -> tuple[str, str]:
    """Return (family, style) if FreeType can load and render with the file."""
    font = ImageFont.truetype(str(path), size=24)
    font.getbbox("Sample Name")
    family, style = font.getname()
    return family or path.stem, style or "Regular"


class FontRegistry:
    def __init__(self, bundled_dir: Path = FONTS_DIR, include_system: bool = True):
        self._fonts: dict[str, FontEntry] = {}
        self._load_bundled(bundled_dir)
        if include_system:
            self._load_system()
        # Always available fallback so the app works even with no font files at all.
        self._add(FontEntry("builtin:default", "Pillow default (Aileron)", "sans-serif", "builtin", None))

    def _add(self, entry: FontEntry) -> None:
        self._fonts.setdefault(entry.id, entry)

    def _load_bundled(self, directory: Path) -> None:
        for font_id, family, category, _, candidates in BUNDLED_FONTS:
            path = next((directory / c for c in candidates if (directory / c).is_file()), None)
            if path is None:
                continue
            instances = _variable_instances(path) if "[" in path.name else []
            if instances:
                for inst in instances:
                    self._add(FontEntry(f"{font_id}:{inst}", f"{family} {inst}", category, "bundled", path, 0, inst))
            else:
                self._add(FontEntry(font_id, family, category, "bundled", path))

    def _load_system(self) -> None:
        files = _index_system_files()
        for name, category, candidates in SYSTEM_FONTS:
            path = next((files[c.lower()] for c in candidates if c.lower() in files), None)
            if path is not None:
                self._add(FontEntry(f"system:{_slug(name)}", name, category, "system", path))

    def list(self) -> list[FontEntry]:
        return list(self._fonts.values())

    def get(self, font_id: str) -> Optional[FontEntry]:
        return self._fonts.get(font_id)

    def default_id(self) -> str:
        for font_id in DEFAULT_FONT_IDS:
            if font_id in self._fonts:
                return font_id
        return next(iter(self._fonts))

"""Text layout and drawing on top of the ORIGINAL certificate template.

The template pixels are never redrawn or re-synthesised: every certificate is a copy of the
decoded template with text drawn on top, saved losslessly as PNG at the same dimensions.

Layout model
------------
* The user defines a text box (x, y, width, height) in template pixels.
* The name is drawn at the preferred font size. If it does not fit, the size is reduced
  (down to min_font_size). If it still does not fit, the text is wrapped onto up to
  max_lines balanced lines, again searching for the largest size that fits.
* Vertical placement uses a fixed reference glyph extent per font/size, so every student
  with a one-line name gets exactly the same baseline regardless of letters like "g" or "y".
* Horizontal alignment uses the real ink extent, so centred names are visually centred.
"""

from __future__ import annotations

import io
import itertools
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import img2pdf
from PIL import Image, ImageDraw, ImageFont, features

from .models import TextStyle

LAYOUT_ENGINE = ImageFont.Layout.RAQM if features.check_feature("raqm") else ImageFont.Layout.BASIC
REFERENCE_GLYPHS = "HÁgjy"   # cap height + accent + descenders, used for stable vertical metrics
TOLERANCE = 0.5              # pixels of slack when testing whether ink fits in the box
MAX_PARTITIONS = 2000        # beyond this many split candidates, fall back to greedy wrapping


# Scripts that need OpenType shaping (raqm) to render correctly: Hebrew, Arabic, Syriac, Thaana,
# Indic (Devanagari … Malayalam, Sinhala), Thai, Lao, Tibetan, Myanmar, Khmer.
_COMPLEX_SCRIPT = re.compile("[֐-ࣿऀ-෿฀-࿿က-႟ក-៿]")


def shaping_warning(text: str) -> Optional[str]:
    if LAYOUT_ENGINE == ImageFont.Layout.BASIC and _COMPLEX_SCRIPT.search(text):
        return ("This text uses a script that needs complex shaping (e.g. Tamil, Hindi, Arabic), but the "
                "raqm library is not available, so letters may not join correctly. See README → Complex scripts.")
    return None


class TemplateError(ValueError):
    """Raised when a template image cannot be used."""


@dataclass(frozen=True)
class FontSpec:
    path: Optional[str]        # None = Pillow's built-in default font
    index: int = 0             # face index for .ttc collections
    variation: Optional[str] = None  # named instance for variable fonts, e.g. "Bold"


@dataclass
class PlacedLine:
    text: str
    x: float          # drawing origin x (anchor "ls" = left edge of advance, baseline)
    baseline: float   # baseline y
    ink: tuple[float, float, float, float]


@dataclass
class TextLayout:
    text: str
    font_size: int
    lines: list[PlacedLine]
    fits: bool
    shrunk: bool = False
    wrapped: bool = False
    extent: tuple[float, float, float, float] = (0, 0, 0, 0)  # union of ink + reference metrics

    def within(self, width: int, height: int) -> bool:
        left, top, right, bottom = self.extent
        return left >= -TOLERANCE and top >= -TOLERANCE and right <= width + TOLERANCE and bottom <= height + TOLERANCE

    def to_dict(self) -> dict[str, Any]:
        return {
            "font_size": self.font_size,
            "lines": [line.text for line in self.lines],
            "fits": self.fits,
            "shrunk": self.shrunk,
            "wrapped": self.wrapped,
            "extent": [round(v, 1) for v in self.extent],
        }


# --------------------------------------------------------------------------- fonts

_local = threading.local()


def load_font(spec: FontSpec, size: int) -> ImageFont.FreeTypeFont:
    """Load (and cache per thread; FreeType faces are not thread-safe) a font at a size."""
    cache: dict = getattr(_local, "fonts", None)
    if cache is None:
        cache = _local.fonts = {}
    key = (spec, size)
    font = cache.get(key)
    if font is None:
        if len(cache) > 256:
            cache.clear()
        if spec.path is None:
            font = ImageFont.load_default(size=size)
        else:
            font = ImageFont.truetype(spec.path, size=size, index=spec.index, layout_engine=LAYOUT_ENGINE)
            if spec.variation:
                font.set_variation_by_name(spec.variation)
        cache[key] = font
    return font


# --------------------------------------------------------------------------- layout

def _place(font: ImageFont.FreeTypeFont, lines: list[str], style: TextStyle, size: int, text: str) -> TextLayout:
    box = style.box
    ascent, descent = font.getmetrics()
    _, ref_top, _, ref_bottom = font.getbbox(REFERENCE_GLYPHS, anchor="ls")
    line_height = (ascent + descent) * style.line_spacing
    block_height = (ref_bottom - ref_top) + line_height * (len(lines) - 1)

    if style.vertical_align == "top":
        top = box.y
    elif style.vertical_align == "bottom":
        top = box.y + box.height - block_height
    else:
        top = box.y + (box.height - block_height) / 2

    placed: list[PlacedLine] = []
    for i, line in enumerate(lines):
        baseline = top - ref_top + i * line_height
        left, ink_top, right, ink_bottom = font.getbbox(line, anchor="ls")
        ink_width = right - left
        if style.align == "left":
            ink_left = box.x
        elif style.align == "right":
            ink_left = box.x + box.width - ink_width
        else:
            ink_left = box.x + (box.width - ink_width) / 2
        x = ink_left - left
        placed.append(PlacedLine(line, x, baseline, (x + left, baseline + ink_top, x + right, baseline + ink_bottom)))

    extent = (
        min(p.ink[0] for p in placed),
        min(min(p.ink[1] for p in placed), top),
        max(p.ink[2] for p in placed),
        max(max(p.ink[3] for p in placed), top + block_height),
    )
    # A glyph that reaches beyond the reference extent (e.g. a long swash on a script "Y") must
    # not force a smaller size when the text is short enough: nudge just this text back inside.
    if extent[3] - extent[1] <= box.height + TOLERANCE:
        shift = max(0.0, box.y - extent[1]) or min(0.0, box.y + box.height - extent[3])
        if shift:
            placed = [PlacedLine(p.text, p.x, p.baseline + shift, (p.ink[0], p.ink[1] + shift, p.ink[2], p.ink[3] + shift)) for p in placed]
            extent = (extent[0], extent[1] + shift, extent[2], extent[3] + shift)
    fits = (
        extent[0] >= box.x - TOLERANCE
        and extent[1] >= box.y - TOLERANCE
        and extent[2] <= box.x + box.width + TOLERANCE
        and extent[3] <= box.y + box.height + TOLERANCE
    )
    return TextLayout(text=text, font_size=size, lines=placed, fits=fits, extent=extent)


def _partition(words: list[str], n_lines: int, font: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    """Split words into n_lines lines, minimising the widest line (balanced wrapping)."""
    gaps = len(words) - 1
    combos = 1
    for k in range(n_lines - 1):
        combos = combos * (gaps - k) // (k + 1)
    if combos <= MAX_PARTITIONS:
        best, best_width = None, float("inf")
        for cuts in itertools.combinations(range(1, len(words)), n_lines - 1):
            bounds = (0, *cuts, len(words))
            lines = [" ".join(words[a:b]) for a, b in zip(bounds, bounds[1:])]
            width = max(font.getlength(line) for line in lines)
            if width < best_width:
                best, best_width = lines, width
        return best  # type: ignore[return-value]
    # Greedy fallback for extremely long texts.
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if current and font.getlength(trial) > max_width and len(lines) < n_lines - 1:
            lines.append(current)
            current = word
        else:
            current = trial
    lines.append(current)
    return lines


def _largest_fitting(text: str, spec: FontSpec, style: TextStyle, make_lines) -> Optional[TextLayout]:
    """Binary-search the largest size in [min_font_size, font_size] whose layout fits."""

    def attempt(size: int) -> TextLayout:
        font = load_font(spec, size)
        return _place(font, make_lines(font), style, size, text)

    top = attempt(style.font_size)
    if top.fits:
        return top
    lo, hi, best = style.min_font_size, style.font_size - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        layout = attempt(mid)
        if layout.fits:
            best, lo = layout, mid + 1
        else:
            hi = mid - 1
    return best


def layout_text(text: str, spec: FontSpec, style: TextStyle) -> TextLayout:
    text = text.strip()
    if not text:
        raise ValueError("cannot lay out empty text")

    layout = _largest_fitting(text, spec, style, lambda font: [text])
    if layout:
        layout.shrunk = layout.font_size < style.font_size
        return layout

    words = text.split(" ")
    if style.allow_wrap and style.max_lines > 1 and len(words) > 1:
        for n_lines in range(2, min(style.max_lines, len(words)) + 1):
            layout = _largest_fitting(
                text, spec, style, lambda font, n=n_lines: _partition(words, n, font, style.box.width)
            )
            if layout:
                layout.wrapped = True
                layout.shrunk = layout.font_size < style.font_size
                return layout

    # Nothing fits: use the smallest size and the most compact option, flagged as overflow.
    font = load_font(spec, style.min_font_size)
    candidates = [_place(font, [text], style, style.min_font_size, text)]
    if style.allow_wrap and style.max_lines > 1 and len(words) > 1:
        n = min(style.max_lines, len(words))
        candidates.append(_place(font, _partition(words, n, font, style.box.width), style, style.min_font_size, text))
        candidates[-1].wrapped = True

    def overflow(lay: TextLayout) -> float:
        b = style.box
        return max(0, b.x - lay.extent[0]) + max(0, lay.extent[2] - b.x - b.width) + \
            max(0, b.y - lay.extent[1]) + max(0, lay.extent[3] - b.y - b.height)

    layout = min(candidates, key=overflow)
    layout.shrunk = style.min_font_size < style.font_size
    return layout


# --------------------------------------------------------------------------- drawing

def hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def draw_layout(img: Image.Image, layout: TextLayout, spec: FontSpec, color: str) -> None:
    font = load_font(spec, layout.font_size)
    fill: tuple[int, ...] = hex_to_rgb(color)
    if img.mode == "RGBA":
        fill = (*fill, 255)
    draw = ImageDraw.Draw(img)
    for line in layout.lines:
        draw.text((line.x, line.baseline), line.text, font=font, fill=fill, anchor="ls")


@dataclass
class TextField:
    text: str
    spec: FontSpec
    style: TextStyle


@dataclass
class Template:
    image: Image.Image                       # decoded original, never modified in place
    save_options: dict[str, Any] = field(default_factory=dict)
    original_mode: str = ""

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size


def load_template(path: Path) -> Template:
    """Decode the PNG once. Only the colour mode may be widened (e.g. palette -> RGB) so text
    can be drawn in full colour; the visible pixels stay identical."""
    try:
        with Image.open(path) as im:
            im.load()
            info = dict(im.info)
            mode = im.mode
            has_alpha = mode in ("RGBA", "LA", "PA") or "transparency" in info
            if mode == "RGBA" or (mode == "RGB" and not has_alpha):
                image = im.copy()
            elif has_alpha:
                image = im.convert("RGBA")
            elif mode.startswith("I;16") or mode == "I":
                image = im.point(lambda v: v / 256).convert("L").convert("RGB")
            else:
                image = im.convert("RGB")
    except (OSError, ValueError) as exc:
        raise TemplateError(f"Could not decode the template image: {exc}") from exc

    save_options: dict[str, Any] = {}
    dpi = info.get("dpi")
    if dpi and all(float(d) > 0 for d in dpi):
        save_options["dpi"] = tuple(round(float(d)) for d in dpi)
    if info.get("icc_profile"):
        save_options["icc_profile"] = info["icc_profile"]
    return Template(image=image, save_options=save_options, original_mode=mode)


def render_certificate(template: Template, fields: list[TextField]) -> tuple[Image.Image, list[TextLayout]]:
    image = template.image.copy()
    layouts = []
    for fld in fields:
        layout = layout_text(fld.text, fld.spec, fld.style)
        draw_layout(image, layout, fld.spec, fld.style.color)
        layouts.append(layout)
    return image, layouts


def save_png(image: Image.Image, path: Path, template: Template) -> None:
    image.save(path, format="PNG", compress_level=6, **template.save_options)


def pdf_bytes(image: Image.Image, dpi: Optional[tuple] = None) -> bytes:
    """Lossless single-page PDF (img2pdf embeds the pixels without JPEG re-compression)."""
    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")  # PDF pages have no transparency: flatten onto white
        flat = Image.new("RGB", image.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        image = flat
    elif image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=1, dpi=dpi or (96, 96))
    return img2pdf.convert(buffer.getvalue())


def save_pdf(image: Image.Image, path: Path, template: Template) -> None:
    path.write_bytes(pdf_bytes(image, template.save_options.get("dpi")))

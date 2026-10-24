from __future__ import annotations

import pytest
from PIL import Image, ImageChops, ImageFont

from app.fonts import FONTS_DIR, FontRegistry
from app.renderer import LAYOUT_ENGINE, Template, TextField, layout_text, render_certificate, shaping_warning
from conftest import DEFAULT_FONT, style


def ink_bbox(image: Image.Image, background=(255, 255, 255)):
    diff = ImageChops.difference(image.convert("RGB"), Image.new("RGB", image.size, background))
    return diff.getbbox()


def blank_template(size=(1200, 800)) -> Template:
    return Template(image=Image.new("RGB", size, "white"))


def test_short_name_uses_preferred_size():
    layout = layout_text("Asha Rao", DEFAULT_FONT, style(size=80))
    assert layout.font_size == 80
    assert layout.fits and not layout.shrunk and not layout.wrapped
    assert len(layout.lines) == 1


@pytest.mark.parametrize("align", ["left", "center", "right"])
def test_horizontal_alignment(align):
    s = style(align=align)
    layout = layout_text("Maximilian Okonkwo", DEFAULT_FONT, s)
    left, _, right, _ = layout.lines[0].ink
    if align == "left":
        assert left == pytest.approx(s.box.x, abs=0.01)
    elif align == "right":
        assert right == pytest.approx(s.box.x + s.box.width, abs=0.01)
    else:
        assert (left + right) / 2 == pytest.approx(s.box.x + s.box.width / 2, abs=0.01)


def test_rendered_pixels_stay_inside_box_and_are_centred():
    s = style(x=200, y=300, width=800, height=140, size=90)
    image, layouts = render_certificate(blank_template(), [TextField("Priya Venkataraman", DEFAULT_FONT, s)])
    bbox = ink_bbox(image)
    assert bbox is not None
    left, top, right, bottom = bbox
    assert left >= s.box.x - 1 and right <= s.box.x + s.box.width + 1
    assert top >= s.box.y - 1 and bottom <= s.box.y + s.box.height + 1
    assert abs((left + right) / 2 - (s.box.x + s.box.width / 2)) <= 2


def test_long_name_shrinks_to_fit():
    s = style(width=600, size=100, min_size=20)
    layout = layout_text("Alexandria Konstantinopoulou-Papadimitriou", DEFAULT_FONT, s)
    assert layout.fits and layout.shrunk and not layout.wrapped
    assert 20 <= layout.font_size < 100
    assert layout.extent[2] - layout.extent[0] <= s.box.width + 0.5
    # The chosen size is the largest that fits: one size larger must not fit on one line.
    bigger = layout_text("Alexandria Konstantinopoulou-Papadimitriou", DEFAULT_FONT,
                         style(width=600, size=layout.font_size + 1, min_size=layout.font_size + 1, allow_wrap=False))
    assert not bigger.fits


def test_very_long_name_wraps_onto_balanced_lines():
    s = style(x=50, width=700, height=260, size=70, min_size=50)
    text = "Venkata Lakshmi Narasimha Subrahmanya Sharma"
    layout = layout_text(text, DEFAULT_FONT, s)
    assert layout.fits and layout.wrapped
    assert len(layout.lines) == 2
    assert " ".join(line.text for line in layout.lines) == text
    image, _ = render_certificate(blank_template(), [TextField(text, DEFAULT_FONT, s)])
    left, top, right, bottom = ink_bbox(image)
    assert left >= s.box.x - 1 and right <= s.box.x + s.box.width + 1
    assert top >= s.box.y - 1 and bottom <= s.box.y + s.box.height + 1


def test_overflow_is_reported_when_nothing_fits():
    s = style(width=200, size=60, min_size=50, allow_wrap=False)
    layout = layout_text("Bartholomew Fitzgerald-Montgomery", DEFAULT_FONT, s)
    assert not layout.fits
    assert layout.font_size == 50


def test_same_baseline_for_every_single_line_name():
    s = style()
    baselines = {layout_text(name, DEFAULT_FONT, s).lines[0].baseline for name in ["Amy", "Peggy Jay", "ÅSA", "Tom"]}
    assert len(baselines) == 1


@pytest.mark.parametrize("valign", ["top", "middle", "bottom"])
def test_vertical_alignment_stays_in_box(valign):
    s = style(height=300, vertical_align=valign)
    layout = layout_text("Grace Hopper", DEFAULT_FONT, s)
    assert layout.fits
    top, bottom = layout.extent[1], layout.extent[3]
    if valign == "top":
        assert top == pytest.approx(s.box.y, abs=1)
    elif valign == "bottom":
        assert bottom == pytest.approx(s.box.y + s.box.height, abs=1)
    else:
        assert (top + bottom) / 2 == pytest.approx(s.box.y + s.box.height / 2, abs=2)


def test_text_colour_is_applied():
    s = style(size=120)
    s.color = "#ff0000"
    image, _ = render_certificate(blank_template(), [TextField("HELLO", DEFAULT_FONT, s)])
    colours = {c for _, c in image.getcolors(1_000_000)}
    assert (255, 0, 0) in colours


def test_shaping_warning_only_for_complex_scripts_without_raqm():
    assert shaping_warning("José Nguyễn 王小明") is None
    tamil = shaping_warning("அருண் குமார்")
    assert (tamil is not None) == (LAYOUT_ENGINE == ImageFont.Layout.BASIC)


def test_empty_text_rejected():
    with pytest.raises(ValueError):
        layout_text("   ", DEFAULT_FONT, style())


def test_layout_identical_for_all_records_with_same_style():
    s = style()
    first = layout_text("Same Name", DEFAULT_FONT, s)
    second = layout_text("Same Name", DEFAULT_FONT, s)
    assert first.to_dict() == second.to_dict()


@pytest.mark.skipif(not (FONTS_DIR / "GreatVibes-Regular.ttf").exists(), reason="bundled fonts not downloaded")
@pytest.mark.parametrize("valign", ["top", "bottom"])
def test_deep_swash_glyph_does_not_force_minimum_size(valign):
    # Great Vibes' "Y" descends below the reference glyphs; the short name must still fit
    # at (nearly) the preferred size by nudging, not collapse to the minimum size.
    spec = FontRegistry(include_system=False).get("great-vibes").spec
    s = style(x=490, y=730, width=1500, height=260, size=170, min_size=90, vertical_align=valign)
    layout = layout_text("Divya Yılmaz", spec, s)
    assert layout.fits
    assert layout.font_size > 150
    assert s.box.y - 0.5 <= layout.extent[1] and layout.extent[3] <= s.box.y + s.box.height + 0.5


@pytest.mark.skipif(not any(FONTS_DIR.glob("*.ttf")), reason="bundled fonts not downloaded")
def test_bundled_fonts_render():
    registry = FontRegistry(include_system=False)
    entries = [e for e in registry.list() if e.source == "bundled"]
    assert entries
    for entry in entries:
        layout = layout_text("José Nguyễn O'Brien", entry.spec, style(size=60))
        assert layout.fits, entry.id

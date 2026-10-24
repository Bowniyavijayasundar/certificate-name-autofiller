from __future__ import annotations

import sys
from pathlib import Path

import openpyxl
import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import Box, TextStyle  # noqa: E402
from app.renderer import FontSpec  # noqa: E402

DEFAULT_FONT = FontSpec(None)  # Pillow's built-in scalable font: no font files needed for tests


@pytest.fixture
def make_xlsx(tmp_path):
    def _make(rows, name="students.xlsx", extra_sheets=None):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Students"
        for row in rows:
            ws.append(row)
        for title, sheet_rows in (extra_sheets or {}).items():
            extra = wb.create_sheet(title)
            for row in sheet_rows:
                extra.append(row)
        path = tmp_path / name
        wb.save(path)
        return path
    return _make


def make_template(path: Path, size=(1200, 800), mode="RGB") -> Path:
    """A non-uniform template so tests can detect any change to background pixels."""
    w, h = size
    img = Image.linear_gradient("L").resize(size).convert("RGB")
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, w - 11, h - 11], outline=(120, 20, 40), width=8)
    for x in range(0, w, 40):
        draw.line([(x, 0), (x, 30)], fill=(30, 90, 160), width=3)
    if mode != "RGB":
        img = img.convert(mode)
    img.save(path, format="PNG", dpi=(150, 150))
    return path


@pytest.fixture
def template_png(tmp_path):
    return make_template(tmp_path / "template.png")


def style(x=100, y=300, width=1000, height=150, size=80, min_size=30, align="center", **kw) -> TextStyle:
    return TextStyle(
        box=Box(x=x, y=y, width=width, height=height), font_id="builtin:default", font_size=size,
        min_font_size=min_size, color="#1a2b3c", align=align, **kw,
    )


def student_rows(n=100):
    first = ["Aarav", "Bianca", "Chen", "Dmitri", "Élodie", "Farah", "Gökhan", "Hana", "Ines", "Jamal"]
    last = ["Okafor", "Nguyễn", "O'Brien", "Müller-Lüdenscheidt", "Silva", "Kowalski", "Tanaka", "Haddad", "Rossi", "Kaur"]
    rows = [["Student Name", "Department", "Email Address"]]
    for i in range(n):
        name = f"{first[i % 10]} {last[(i // 10) % 10]} {i + 1}"
        rows.append([name, f"Dept {i % 5}", f"student{i + 1}@example.edu"])
    return rows

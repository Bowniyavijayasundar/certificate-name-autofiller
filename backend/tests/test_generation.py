from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from app.excel_parser import parse_workbook
from app.fonts import FontEntry
from app.jobs import Job, run_job
from app.models import CertificateConfig, ColumnMapping, OutputFormats
from app.renderer import TextField, load_template, render_certificate
from app.storage import UniqueNamer, safe_filename_stem
from conftest import DEFAULT_FONT, make_template, student_rows, style

BUILTIN = FontEntry("builtin:default", "Default", "sans-serif", "builtin", None)


def resolve(font_id: str) -> FontEntry:
    assert font_id == "builtin:default"
    return BUILTIN


def config(**overrides) -> CertificateConfig:
    data = dict(mapping=ColumnMapping(name_column="Student Name", department_column="Department"),
                name=style(x=100, y=300, width=1000, height=150, size=72, min_size=28))
    data.update(overrides)
    return CertificateConfig(**data)


def run(tmp_path: Path, xlsx: Path, template: Path, cfg: CertificateConfig, formats=OutputFormats()) -> Job:
    records = parse_workbook(xlsx).records
    job = Job(id="a" * 32, session_id="b" * 32, dir=tmp_path / "job", formats=formats, total=len(records))
    run_job(job, template, records, cfg, resolve, workers=4)
    return job


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_one_hundred_students_generate_one_hundred_correct_certificates(tmp_path, make_xlsx, template_png):
    template_hash = sha256(template_png)
    cfg = config()
    job = run(tmp_path, make_xlsx(student_rows(100)), template_png, cfg)

    assert job.status == "completed", job.error
    assert job.processed == job.total == 100
    assert [r.status for r in job.results] == ["generated"] * 100
    assert [r.row_number for r in job.results] == list(range(2, 102))       # Excel row order kept

    pngs = sorted((job.dir / "png").glob("*.png"))
    assert len(pngs) == 100
    assert len({r.png for r in job.results}) == 100                          # unique file names
    assert sha256(template_png) == template_hash                             # template untouched on disk

    template = load_template(template_png)
    with Image.open(template_png) as original:
        original_rgb = original.convert("RGB")
        original_dpi = original.info["dpi"]
    box = cfg.name.box
    for result in job.results:
        with Image.open(job.files[result.png]) as out:
            assert out.size == original_rgb.size                               # dimensions preserved
            assert out.info.get("dpi") == pytest.approx(original_dpi)          # resolution metadata kept
            out_rgb = out.convert("RGB")
        # The correct student's name: identical to an independent render of THIS row's name.
        expected, _ = render_certificate(template, [TextField(result.name, DEFAULT_FONT, cfg.name)])
        assert ImageChops.difference(out_rgb, expected.convert("RGB")).getbbox() is None, result.name
        # Background outside the text box is pixel-identical to the original template.
        diff = ImageChops.difference(out_rgb, original_rgb).getbbox()
        assert diff is not None
        assert diff[0] >= box.x - 1 and diff[1] >= box.y - 1
        assert diff[2] <= box.x + box.width + 1 and diff[3] <= box.y + box.height + 1


def test_zip_contains_every_certificate_and_report(tmp_path, make_xlsx, template_png):
    job = run(tmp_path, make_xlsx(student_rows(100)), template_png, config(), OutputFormats(png=True, pdf=True))
    with zipfile.ZipFile(job.zip_path) as zf:
        names = zf.namelist()
        assert len([n for n in names if n.endswith(".png")]) == 100
        assert len([n for n in names if n.startswith("pdf/") and n.endswith(".pdf")]) == 100
        assert zf.read(names[names.index("pdf/" + job.results[0].pdf)]).startswith(b"%PDF")
        report = list(csv.DictReader(io.StringIO(zf.read("generation_report.csv").decode("utf-8-sig"))))
    assert len(report) == 100
    assert [row["Student Name"] for row in report] == [r.name for r in job.results]
    assert all(row["Status"] == "generated" for row in report)


def test_blank_names_are_reported_not_silently_skipped(tmp_path, make_xlsx, template_png):
    rows = [["Student Name", "Department"], ["Asha Rao", "CSE"], [None, "EEE"], ["Asha Rao", "IT"], ["asha rao", "ECE"]]
    job = run(tmp_path, make_xlsx(rows), template_png, config())
    statuses = [(r.row_number, r.status) for r in job.results]
    assert statuses == [(2, "generated"), (3, "skipped"), (4, "generated"), (5, "generated")]
    assert "Blank name" in job.results[1].message
    assert [r.png for r in job.results if r.png] == [
        "Asha_Rao_Certificate.png", "Asha_Rao_2_Certificate.png", "asha_rao_3_Certificate.png",
    ]
    snapshot = job.snapshot()
    assert snapshot["counts"]["generated"] == 3 and snapshot["counts"]["skipped"] == 1


def test_department_text_is_optional_and_drawn_when_enabled(tmp_path, make_xlsx, template_png):
    cfg = config(department_enabled=True, department=style(x=300, y=500, width=600, height=60, size=36, min_size=16))
    job = run(tmp_path, make_xlsx(student_rows(3)), template_png, cfg)
    assert job.status == "completed"
    with Image.open(template_png) as original, Image.open(job.files[job.results[0].png]) as out:
        diff = ImageChops.difference(out.convert("RGB"), original.convert("RGB")).getbbox()
    assert diff[3] > 500  # pixels changed inside the department box as well


def test_name_that_would_be_clipped_fails_with_explanation(tmp_path, make_xlsx, template_png):
    cfg = config(name=style(x=1100, y=300, width=100, height=100, size=60, min_size=60, allow_wrap=False, align="left"))
    job = run(tmp_path, make_xlsx([["Student Name"], ["Extraordinarily Long Student Name"]]), template_png, cfg)
    assert job.results[0].status == "failed"
    assert "cut off" in job.results[0].message
    assert job.status == "completed"


def test_palette_and_transparent_templates_keep_their_look(tmp_path, make_xlsx):
    template = make_template(tmp_path / "palette.png", mode="P")
    job = run(tmp_path, make_xlsx(student_rows(1)), template, config())
    with Image.open(template) as original, Image.open(job.files[job.results[0].png]) as out:
        assert out.size == original.size
        diff = ImageChops.difference(out.convert("RGB"), original.convert("RGB")).getbbox()
    assert diff[1] >= 299 and diff[3] <= 451


@pytest.mark.parametrize("raw, expected", [
    ("Asha Rao", "Asha_Rao"),
    ("../../etc/passwd", "etcpasswd"),
    ('Bad<>:"/\\|?*Name', "BadName"),
    ("CON", "_CON"),
    ("José   Ávila", "José_Ávila"),
    ("அருண் குமார்", "அருண்_குமார்"),
    ("...", ""),
])
def test_safe_filename_stem(raw, expected):
    assert safe_filename_stem(raw) == expected


def test_unique_namer_is_case_insensitive():
    namer = UniqueNamer()
    assert [namer.allocate(s) for s in ["Ann", "ann", "ANN", "Ann_2"]] == [
        "Ann_Certificate", "ann_2_Certificate", "ANN_3_Certificate", "Ann_2_2_Certificate",
    ]

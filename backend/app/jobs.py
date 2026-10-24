"""Certificate generation: per-record planning, layout checks and background bulk jobs."""

from __future__ import annotations

import csv
import io
import logging
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .excel_parser import StudentRecord
from .fonts import FontEntry
from .models import CertificateConfig, OutputFormats
from .renderer import (
    Template, TextField, TextLayout, layout_text, load_template, render_certificate, save_pdf, save_png,
    shaping_warning,
)
from .storage import UniqueNamer, safe_filename_stem

log = logging.getLogger(__name__)

FontResolver = Callable[[str], FontEntry]


class ConfigError(ValueError):
    """Invalid configuration for the current template / sheet."""


# --------------------------------------------------------------------------- shared helpers

def check_config(config: CertificateConfig, columns: list[str], template_size: tuple[int, int], resolve: FontResolver) -> None:
    width, height = template_size
    mapping = config.mapping
    if mapping.name_column not in columns:
        raise ConfigError(f"Name column {mapping.name_column!r} does not exist in the sheet.")
    if config.department_enabled and mapping.department_column not in columns:
        raise ConfigError(f"Department column {mapping.department_column!r} does not exist in the sheet.")
    styles = [("Name", config.name)] + ([("Department", config.department)] if config.department_enabled else [])
    for label, style in styles:
        box = style.box
        if box.x + box.width > width + 1 or box.y + box.height > height + 1:
            raise ConfigError(f"{label} text box extends beyond the template ({width}x{height} px).")
        resolve(style.font_id)  # raises if unknown


def build_fields(record: StudentRecord, config: CertificateConfig, resolve: FontResolver) -> list[TextField]:
    name = record.values.get(config.mapping.name_column, "")
    fields = [TextField(name, resolve(config.name.font_id).spec, config.name)]
    if config.department_enabled and config.department and config.mapping.department_column:
        department = record.values.get(config.mapping.department_column, "")
        if department:
            fields.append(TextField(department, resolve(config.department.font_id).spec, config.department))
    return fields


def layout_issues(layout: TextLayout, template_size: tuple[int, int], label: str) -> tuple[Optional[str], list[str]]:
    """Return (error, warnings) for a computed layout."""
    if not layout.within(*template_size):
        return f"{label} would be cut off at the edge of the certificate. Enlarge the text box or lower the minimum font size.", []
    warnings = []
    shaping = shaping_warning(layout.text)
    if shaping:
        warnings.append(f"{label}: {shaping}")
    if not layout.fits:
        warnings.append(f"{label} is larger than its text box even at the minimum font size.")
    elif layout.wrapped:
        warnings.append(f"{label} was wrapped onto {len(layout.lines)} lines.")
    elif layout.shrunk:
        warnings.append(f"{label} font reduced to {layout.font_size}px to fit.")
    return None, warnings


def assess_records(records: list[StudentRecord], config: CertificateConfig, resolve: FontResolver, template_size: tuple[int, int]) -> dict:
    """Dry run of the layout for every record (no drawing) to warn before generation."""
    report = {"shrunk": [], "wrapped": [], "overflow": [], "clipped": [], "department_issues": [], "shaping": []}
    for record in records:
        fields = build_fields(record, config, resolve)
        if not fields[0].text:
            continue
        for i, fld in enumerate(fields):
            layout = layout_text(fld.text, fld.spec, fld.style)
            entry = {"row": record.row_number, "text": fld.text, "font_size": layout.font_size}
            if shaping_warning(fld.text):
                report["shaping"].append(entry)
            if i > 0:
                if not layout.fits or not layout.within(*template_size):
                    report["department_issues"].append(entry)
                continue
            if not layout.within(*template_size):
                report["clipped"].append(entry)
            elif not layout.fits:
                report["overflow"].append(entry)
            elif layout.wrapped:
                report["wrapped"].append(entry)
            elif layout.shrunk:
                report["shrunk"].append(entry)
    return report


# --------------------------------------------------------------------------- jobs

@dataclass
class CertificateResult:
    index: int
    row_number: int
    name: str
    department: str = ""
    status: str = "pending"          # pending | generated | skipped | failed | cancelled
    message: str = ""
    warnings: list[str] = field(default_factory=list)
    png: Optional[str] = None
    pdf: Optional[str] = None
    font_size: Optional[int] = None
    lines: Optional[int] = None


@dataclass
class Job:
    id: str
    session_id: str
    dir: Path
    formats: OutputFormats
    total: int = 0
    status: str = "queued"           # queued | running | completed | cancelled | failed
    processed: int = 0
    results: list[CertificateResult] = field(default_factory=list)
    files: dict[str, Path] = field(default_factory=dict)   # download name -> path on disk
    zip_path: Optional[Path] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    records: list[StudentRecord] = field(default_factory=list)     # source rows (for e-mail lookup)
    email_sent: dict[int, dict] = field(default_factory=dict)      # record index -> {to, at, email_job_id}

    @property
    def is_active(self) -> bool:
        return self.status in ("queued", "running")

    def snapshot(self, include_results: bool = True) -> dict:
        with self.lock:
            counts = {s: 0 for s in ("generated", "skipped", "failed", "cancelled", "pending")}
            for res in self.results:
                counts[res.status] = counts.get(res.status, 0) + 1
            end = self.finished_at or time.time()
            data = {
                "job_id": self.id,
                "status": self.status,
                "total": self.total,
                "processed": self.processed,
                "counts": counts,
                "with_warnings": sum(1 for r in self.results if r.warnings and r.status == "generated"),
                "formats": self.formats.model_dump(),
                "zip_available": self.zip_path is not None and self.zip_path.is_file(),
                "emails_sent": len(self.email_sent),
                "error": self.error,
                "elapsed_seconds": round(end - self.started_at, 2) if self.started_at else 0,
            }
            if include_results:
                data["results"] = [asdict(r) for r in self.results]
            return data


def _csv_safe(value: object) -> str:
    """Prevent spreadsheet formula injection when the report is opened in Excel."""
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _write_report(job: Job, path: Path) -> None:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Excel Row", "Student Name", "Department", "Status", "PNG File", "PDF File", "Font Size", "Message"])
    for r in job.results:
        message = "; ".join(filter(None, [r.message, *r.warnings]))
        writer.writerow([r.row_number, _csv_safe(r.name), _csv_safe(r.department), r.status,
                         r.png or "", f"pdf/{r.pdf}" if r.pdf else "", r.font_size or "", _csv_safe(message)])
    path.write_text(buffer.getvalue(), encoding="utf-8-sig")


def _build_zip(job: Job, report_path: Path) -> Path:
    zip_path = job.dir / f"certificates_{job.id[:8]}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        for r in job.results:
            if r.status != "generated":
                continue
            if r.png:
                zf.write(job.files[r.png], arcname=r.png)
            if r.pdf:
                zf.write(job.files[r.pdf], arcname=f"pdf/{r.pdf}")
        zf.write(report_path, arcname="generation_report.csv", compress_type=zipfile.ZIP_DEFLATED)
    return zip_path


def _render_one(job: Job, result: CertificateResult, fields: list[TextField], template: Template, base_name: str) -> None:
    if job.cancel_event.is_set():
        result.status, result.message = "cancelled", "Generation was cancelled before this certificate."
        return
    image, layouts = render_certificate(template, fields)
    error, warnings = layout_issues(layouts[0], template.size, "Name")
    for layout in layouts[1:]:
        dep_error, dep_warnings = layout_issues(layout, template.size, "Department")
        warnings += [dep_error] if dep_error else dep_warnings
    if error:
        result.status, result.message = "failed", error
        return
    if image.size != template.size:  # defensive: output must keep the template's dimensions
        result.status, result.message = "failed", "Output size differs from the template."
        return

    result.font_size, result.lines, result.warnings = layouts[0].font_size, len(layouts[0].lines), warnings
    if job.formats.png:
        name = f"{base_name}.png"
        path = job.dir / "png" / name
        save_png(image, path, template)
        result.png = name
    if job.formats.pdf:
        name = f"{base_name}.pdf"
        path = job.dir / "pdf" / name
        save_pdf(image, path, template)
        result.pdf = name
    result.status = "generated"


def run_job(job: Job, template_path: Path, records: list[StudentRecord], config: CertificateConfig,
            resolve: FontResolver, workers: int) -> None:
    """Executed in a background thread. Every record ends with an explicit status."""
    job.status, job.started_at = "running", time.time()
    try:
        (job.dir / "png").mkdir(parents=True, exist_ok=True)
        (job.dir / "pdf").mkdir(parents=True, exist_ok=True)
        template = load_template(template_path)
        namer = UniqueNamer()
        tasks: list[tuple[CertificateResult, list[TextField], str]] = []

        dept_col = config.mapping.department_column
        for record in records:  # results stay in Excel row order: index i <-> record i
            fields = build_fields(record, config, resolve)
            result = CertificateResult(
                index=record.index, row_number=record.row_number, name=fields[0].text,
                department=record.values.get(dept_col, "") if dept_col else "",
            )
            job.results.append(result)
            if not result.name:
                result.status, result.message = "skipped", "Blank name in the selected name column."
                job.processed += 1
                continue
            stem = safe_filename_stem(result.name) or f"Row_{record.row_number}"
            tasks.append((result, fields, namer.allocate(stem)))
            if config.department_enabled and not result.department:
                result.warnings.append("Department is blank; only the name was printed.")

        with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="render") as pool:
            futures = {pool.submit(_render_one, job, res, flds, template, base): res for res, flds, base in tasks}
            for future in as_completed(futures):
                result = futures[future]
                try:
                    future.result()
                except Exception as exc:  # report, never silently skip
                    log.exception("Rendering failed for row %s", result.row_number)
                    result.status, result.message = "failed", f"Rendering error: {exc}"
                with job.lock:
                    job.processed += 1
                    if result.png:
                        job.files[result.png] = job.dir / "png" / result.png
                    if result.pdf:
                        job.files[result.pdf] = job.dir / "pdf" / result.pdf

        report_path = job.dir / "generation_report.csv"
        _write_report(job, report_path)
        job.files["generation_report.csv"] = report_path
        job.zip_path = _build_zip(job, report_path)
        job.status = "cancelled" if job.cancel_event.is_set() else "completed"
    except Exception as exc:
        log.exception("Job %s failed", job.id)
        job.error = str(exc) or exc.__class__.__name__
        job.status = "failed"
        for result in job.results:
            if result.status == "pending":
                result.status, result.message = "failed", "Job stopped before this certificate was generated."
    finally:
        job.finished_at = time.time()

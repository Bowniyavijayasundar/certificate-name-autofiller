"""FastAPI application: Certificate Name Autofiller API (all routes under /api)."""

from __future__ import annotations

import base64
import io
import logging
import threading
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageFont

from .config import Settings, load_settings
from .excel_parser import ExcelParseError, analyze_records, detect_engine, parse_email_list, parse_workbook
from .fonts import FontEntry, FontRegistry, validate_font_file
from .jobs import (
    ConfigError, FontResolver, Job, assess_records, build_fields, check_config, layout_issues, run_job,
)
from .mailer import (
    DEFAULT_BODY, DEFAULT_SUBJECT, PLACEHOLDERS, PRESETS, EmailError, EmailJob, SmtpSettings, build_message,
    certificate_pdf, describe_smtp_error, open_connection, plan_recipients, render_template, run_email_job,
    summarize, template_values, verify_settings,
)
from .models import (
    AnalyzeRequest, EmailPreviewRequest, EmailSendRequest, EmailTestRequest, GenerateRequest, PreviewRequest,
    ReparseRequest, SmtpConfigRequest, ValidateRequest,
)
from .renderer import LAYOUT_ENGINE, TemplateError, load_template, render_certificate
from .storage import CleanupThread, Session, SessionStore, new_id, safe_display_name

log = logging.getLogger("certificate_autofiller")

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
FONT_MEDIA_TYPES = {".ttf": "font/ttf", ".otf": "font/otf", ".ttc": "font/collection"}
NO_STORE = {"Cache-Control": "no-store"}


def create_app(settings: Optional[Settings] = None, font_registry: Optional[FontRegistry] = None) -> FastAPI:
    settings = settings or load_settings()
    store = SessionStore(settings.sessions_dir, settings.retention_minutes * 60)
    registry = font_registry or FontRegistry()
    Image.MAX_IMAGE_PIXELS = settings.max_template_pixels

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.initialise()
        cleaner = CleanupThread(store, settings.cleanup_interval_seconds)
        cleaner.start()
        yield
        cleaner.stop()
        store.clear_all()  # uploads and outputs never outlive the server process

    app = FastAPI(
        title="Certificate Name Autofiller API",
        version="1.0.0",
        description="Fills student names from an Excel sheet onto an uploaded PNG certificate template.",
        lifespan=lifespan,
    )
    app.state.store = store
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def no_cache(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    for exc_type in (ExcelParseError, TemplateError, ConfigError, EmailError):
        app.add_exception_handler(exc_type, lambda request, exc: JSONResponse(status_code=422, content={"detail": str(exc)}))

    router = APIRouter(prefix="/api")

    # ------------------------------------------------------------------ helpers
    def require_session(session_id: str) -> Session:
        session = store.get(session_id)
        if session is None:
            raise HTTPException(404, "Session not found or expired. Please start again.")
        return session

    def require_job(job_id: str) -> Job:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(404, "Job not found or expired.")
        return job

    def require_inputs(session: Session):
        if session.parsed is None:
            raise HTTPException(409, "Upload an Excel file first.")
        if session.template_path is None:
            raise HTTPException(409, "Upload a certificate template first.")
        if session.template_cache is None:
            session.template_cache = load_template(session.template_path)
        return session.parsed, session.template_cache

    def resolver_for(session: Session) -> FontResolver:
        def resolve(font_id: str) -> FontEntry:
            entry = session.fonts.get(font_id) or registry.get(font_id)
            if entry is None:
                raise ConfigError(f"Unknown font {font_id!r}. Please choose a font from the list.")
            return entry
        return resolve

    def read_upload(request: Request, upload: UploadFile, limit_mb: int, allowed_ext: tuple[str, ...]) -> bytes:
        name = safe_display_name(upload.filename)
        if not name.lower().endswith(allowed_ext):
            raise HTTPException(415, f"Unsupported file type. Allowed: {', '.join(allowed_ext)}")
        limit = limit_mb * 1024 * 1024
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > limit + 1024 * 1024:
            raise HTTPException(413, f"File is too large (limit {limit_mb} MB).")
        data = upload.file.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, f"File is too large (limit {limit_mb} MB).")
        if not data:
            raise HTTPException(400, "The uploaded file is empty.")
        return data

    def excel_payload(session: Session) -> dict:
        parsed = session.parsed
        mapping = parsed.detected_mapping
        analysis = None
        if mapping["name"]:
            analysis = asdict(analyze_records(parsed.records, mapping["name"], mapping["department"], mapping["email"]))
        return {
            "filename": session.excel_filename,
            "sheets": parsed.sheets,
            "sheet": parsed.sheet,
            "header_row": parsed.header_row_number,
            "columns": parsed.columns,
            "detected_mapping": {
                "name_column": mapping["name"],
                "department_column": mapping["department"],
                "email_column": mapping["email"],
            },
            "records": [{"index": r.index, "row_number": r.row_number, "values": r.values} for r in parsed.records],
            "total_records": len(parsed.records),
            "ignored_empty_rows": parsed.ignored_empty_rows,
            "analysis": analysis,
        }

    # ------------------------------------------------------------------ sessions
    @router.get("/health")
    def health():
        return {"status": "ok", "complex_script_shaping": LAYOUT_ENGINE == ImageFont.Layout.RAQM}

    @router.post("/sessions", status_code=201)
    def create_session():
        session = store.create()
        return {"session_id": session.id, "retention_minutes": settings.retention_minutes}

    @router.delete("/sessions/{session_id}")
    def delete_session(session_id: str):
        if not store.delete(session_id):
            raise HTTPException(404, "Session not found or already deleted.")
        return {"deleted": True}

    # ------------------------------------------------------------------ excel
    @router.post("/upload-excel")
    def upload_excel(
        request: Request,
        session_id: str = Form(...),
        file: UploadFile = File(...),
        sheet: Optional[str] = Form(None),
        header_row: str = Form("auto"),
    ):
        session = require_session(session_id)
        data = read_upload(request, file, settings.max_excel_mb, (".xlsx", ".xls"))
        tmp = session.dir / "upload.tmp"
        tmp.write_bytes(data)
        try:
            engine = detect_engine(tmp)
            target = session.dir / ("students.xlsx" if engine == "openpyxl" else "students.xls")
            parsed = parse_workbook(tmp, sheet=sheet or None, header_row=header_row, max_rows=settings.max_rows)
        except ExcelParseError:
            tmp.unlink(missing_ok=True)
            raise
        with session.lock:
            if session.excel_path and session.excel_path != target:
                session.excel_path.unlink(missing_ok=True)
            tmp.replace(target)
            session.excel_path, session.excel_filename, session.parsed = target, safe_display_name(file.filename), parsed
        return excel_payload(session)

    @router.post("/reparse-excel")
    def reparse_excel(req: ReparseRequest):
        session = require_session(req.session_id)
        if session.excel_path is None:
            raise HTTPException(409, "Upload an Excel file first.")
        session.parsed = parse_workbook(session.excel_path, req.sheet, req.header_row, settings.max_rows)
        return excel_payload(session)

    @router.post("/analyze-records")
    def analyze(req: AnalyzeRequest):
        session = require_session(req.session_id)
        if session.parsed is None:
            raise HTTPException(409, "Upload an Excel file first.")
        m = req.mapping
        for col in filter(None, (m.name_column, m.department_column, m.email_column)):
            if col not in session.parsed.columns:
                raise HTTPException(422, f"Column {col!r} does not exist in the sheet.")
        return asdict(analyze_records(session.parsed.records, m.name_column, m.department_column, m.email_column))

    # ------------------------------------------------------------------ template
    @router.post("/upload-template")
    def upload_template(request: Request, session_id: str = Form(...), file: UploadFile = File(...)):
        session = require_session(session_id)
        data = read_upload(request, file, settings.max_template_mb, (".png",))
        if not data.startswith(PNG_MAGIC):
            raise HTTPException(415, "The file is not a valid PNG image.")
        try:
            with Image.open(io.BytesIO(data)) as im:
                if im.format != "PNG":
                    raise HTTPException(415, "The file is not a valid PNG image.")
                width, height = im.size
                if width * height > settings.max_template_pixels:
                    raise HTTPException(413, f"Image is too large ({width}x{height}). Limit: {settings.max_template_pixels:,} pixels.")
                im.verify()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(415, f"The PNG file is corrupt or unsupported: {exc}") from exc

        target = session.dir / "template.png"
        target.write_bytes(data)  # stored byte-for-byte; never modified afterwards
        try:
            template = load_template(target)
        except TemplateError:
            target.unlink(missing_ok=True)
            raise
        with session.lock:
            session.template_path, session.template_cache = target, template
            session.template_info = {
                "filename": safe_display_name(file.filename),
                "width": width,
                "height": height,
                "mode": template.original_mode,
                "dpi": list(template.save_options.get("dpi", [])) or None,
                "file_size": len(data),
            }
        return session.template_info

    @router.get("/template/{session_id}")
    def get_template(session_id: str):
        session = require_session(session_id)
        if session.template_path is None:
            raise HTTPException(404, "No template uploaded.")
        return FileResponse(session.template_path, media_type="image/png", headers=NO_STORE)

    # ------------------------------------------------------------------ fonts
    @router.get("/fonts")
    def list_fonts(session_id: Optional[str] = Query(None)):
        fonts = [f.public() for f in registry.list()]
        if session_id:
            session = require_session(session_id)
            fonts = [f.public() for f in session.fonts.values()] + fonts
        return {"fonts": fonts, "default_font_id": registry.default_id()}

    @router.post("/upload-font")
    def upload_font(request: Request, session_id: str = Form(...), file: UploadFile = File(...)):
        session = require_session(session_id)
        data = read_upload(request, file, settings.max_font_mb, (".ttf", ".otf"))
        suffix = Path(safe_display_name(file.filename)).suffix.lower()
        font_dir = session.dir / "fonts"
        font_dir.mkdir(exist_ok=True)
        font_key = new_id()
        path = font_dir / f"{font_key}{suffix}"
        path.write_bytes(data)
        try:
            family, style = validate_font_file(path)
        except Exception as exc:
            path.unlink(missing_ok=True)
            raise HTTPException(415, f"The font file could not be loaded: {exc}") from exc
        entry = FontEntry(f"upload:{font_key}", f"{family} {style}".strip(), "custom", "uploaded", path)
        session.fonts[entry.id] = entry
        return entry.public()

    @router.get("/fonts/{font_id}/file")
    def font_file(font_id: str, session_id: Optional[str] = Query(None)):
        entry = registry.get(font_id)
        if entry is None and session_id:
            entry = require_session(session_id).fonts.get(font_id)
        if entry is None or entry.path is None:
            raise HTTPException(404, "Font not found.")
        return FileResponse(entry.path, media_type=FONT_MEDIA_TYPES.get(entry.path.suffix.lower(), "application/octet-stream"),
                            headers={"Cache-Control": "private, max-age=3600"})

    # ------------------------------------------------------------------ preview & checks
    @router.post("/preview-certificate")
    def preview_certificate(req: PreviewRequest):
        session = require_session(req.session_id)
        parsed, template = require_inputs(session)
        resolve = resolver_for(session)
        check_config(req.config, parsed.columns, template.size, resolve)
        if req.record_index >= len(parsed.records):
            raise HTTPException(422, "Selected student does not exist.")
        record = parsed.records[req.record_index]
        fields = build_fields(record, req.config, resolve)
        if not fields[0].text:
            raise HTTPException(422, f"Excel row {record.row_number} has a blank name and will be skipped. Choose another student.")

        image, layouts = render_certificate(template, fields)
        error, warnings = layout_issues(layouts[0], template.size, "Name")
        for layout in layouts[1:]:
            dep_error, dep_warnings = layout_issues(layout, template.size, "Department")
            warnings += [dep_error] if dep_error else dep_warnings

        width, height = image.size
        if width > req.max_width:
            image = image.resize((req.max_width, max(1, round(height * req.max_width / width))), Image.LANCZOS, reducing_gap=3.0)
        buffer = io.BytesIO()
        if image.mode == "RGBA":
            image.save(buffer, format="PNG", compress_level=1)
            mime = "image/png"
        else:
            image.save(buffer, format="JPEG", quality=90)
            mime = "image/jpeg"
        return {
            "image": f"data:{mime};base64,{base64.b64encode(buffer.getvalue()).decode()}",
            "width": width,
            "height": height,
            "preview_width": image.width,
            "preview_height": image.height,
            "record": {"index": record.index, "row_number": record.row_number, "name": fields[0].text},
            "name_layout": layouts[0].to_dict(),
            "department_layout": layouts[1].to_dict() if len(layouts) > 1 else None,
            "error": error,
            "warnings": warnings,
        }

    @router.post("/validate-generation")
    def validate_generation(req: ValidateRequest):
        session = require_session(req.session_id)
        parsed, template = require_inputs(session)
        resolve = resolver_for(session)
        check_config(req.config, parsed.columns, template.size, resolve)
        m = req.config.mapping
        analysis = analyze_records(parsed.records, m.name_column, m.department_column, m.email_column)
        fit = assess_records(parsed.records, req.config, resolve, template.size)
        return {
            "total_rows": len(parsed.records),
            "will_generate": analysis.valid_names - len(fit["clipped"]),
            "analysis": asdict(analysis),
            "fit": fit,
        }

    # ------------------------------------------------------------------ generation & downloads
    @router.post("/generate-certificates", status_code=202)
    def generate_certificates(req: GenerateRequest):
        if not req.approved:
            raise HTTPException(400, "Please review the preview and confirm approval before generating.")
        session = require_session(req.session_id)
        parsed, template = require_inputs(session)
        resolve = resolver_for(session)
        check_config(req.config, parsed.columns, template.size, resolve)
        with session.lock:
            for job_id in session.job_ids:
                existing = store.get_job(job_id)
                if existing and existing.is_active:
                    raise HTTPException(409, "A generation job is already running for this session.")
            job_id = new_id()
            job = Job(id=job_id, session_id=session.id, dir=session.dir / "jobs" / job_id, formats=req.formats,
                      total=len(parsed.records), records=list(parsed.records))
            job.dir.mkdir(parents=True)
            store.add_job(session, job)
        threading.Thread(
            target=run_job, name=f"job-{job_id[:8]}", daemon=True,
            args=(job, session.template_path, list(parsed.records), req.config, resolve, settings.max_workers),
        ).start()
        return {"job_id": job_id, "total": job.total}

    @router.get("/jobs/{job_id}")
    def job_status(job_id: str, include_results: bool = True):
        return require_job(job_id).snapshot(include_results)

    @router.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        job = require_job(job_id)
        if job.is_active:
            job.cancel_event.set()
        return {"status": job.status, "cancel_requested": job.cancel_event.is_set()}

    @router.get("/jobs/{job_id}/files/{file_name}")
    def download_file(job_id: str, file_name: str):
        job = require_job(job_id)
        with job.lock:
            path = job.files.get(file_name)  # exact lookup: no user-controlled paths
        if path is None or not path.is_file():
            raise HTTPException(404, "File not found.")
        media = {".png": "image/png", ".pdf": "application/pdf", ".csv": "text/csv"}.get(path.suffix.lower(), "application/octet-stream")
        return FileResponse(path, media_type=media, filename=file_name)

    @router.get("/download-zip/{job_id}")
    def download_zip(job_id: str):
        job = require_job(job_id)
        if job.is_active:
            raise HTTPException(409, "Certificates are still being generated.")
        if job.zip_path is None or not job.zip_path.is_file():
            raise HTTPException(404, "No ZIP archive is available for this job.")
        return FileResponse(job.zip_path, media_type="application/zip", filename="certificates.zip")

    # ------------------------------------------------------------------ e-mail delivery (optional)
    def server_smtp() -> Optional[SmtpSettings]:
        if not settings.smtp_configured:
            return None
        return SmtpSettings(
            host=settings.smtp_host, port=settings.smtp_port, security=settings.smtp_security,
            username=settings.smtp_username, password=settings.smtp_password,
            from_email=settings.smtp_from_email, from_name=settings.smtp_from_name, source="server",
        )

    def require_session_job(session: Session, job_id: str) -> Job:
        job = store.get_job(job_id)
        if job is None or job.session_id != session.id:
            raise HTTPException(404, "Job not found or expired.")
        if job.is_active:
            raise HTTPException(409, "Certificates are still being generated.")
        return job

    def require_smtp(session: Session) -> SmtpSettings:
        if session.email_settings is None:
            raise HTTPException(409, "Connect an e-mail account first.")
        return session.email_settings

    def check_email_column(job: Job, column: str) -> None:
        if job.records and column not in job.records[0].values:
            raise HTTPException(422, f"Column {column!r} does not exist in the sheet.")

    @router.get("/email/config")
    def email_config(session_id: str = Query(...)):
        session = require_session(session_id)
        server = server_smtp()
        return {
            "presets": {k: {key: v[key] for key in ("label", "host", "port", "security", "help")} for k, v in PRESETS.items()},
            "server_config": server.public() if server else None,
            "current": session.email_settings.public() if session.email_settings else None,
            "default_subject": DEFAULT_SUBJECT,
            "default_body": DEFAULT_BODY,
            "placeholders": list(PLACEHOLDERS),
            "delay_seconds": settings.email_delay_seconds,
            "max_per_batch": settings.email_max_per_batch,
        }

    @router.post("/email/config")
    def set_email_config(req: SmtpConfigRequest):
        session = require_session(req.session_id)
        if req.use_server_config:
            smtp = server_smtp()
            if smtp is None:
                raise HTTPException(409, "No SMTP account is configured in the server's .env file.")
        else:
            preset = PRESETS[req.preset]
            from_email = req.from_email.strip()
            username = req.username.strip() or from_email
            password = req.password
            previous = session.email_settings
            if not password and previous and previous.source == "session" and previous.username == username:
                password = previous.password  # editing other fields without retyping the password
            smtp = SmtpSettings(
                host=(req.host.strip() or preset["host"]).lower(),
                port=req.port or preset["port"],
                security=req.security or preset["security"],
                username=username if password else "",
                password=password,
                from_email=from_email,
                from_name=req.from_name.strip(),
                reply_to=req.reply_to.strip(),
            )
        verify_settings(smtp)  # raises EmailError (422) with a readable reason
        session.email_settings = smtp
        return smtp.public()

    @router.delete("/email/config")
    def forget_email_config(session_id: str = Query(...)):
        require_session(session_id).email_settings = None
        return {"forgotten": True}

    @router.post("/email/preview")
    def email_preview(req: EmailPreviewRequest):
        session = require_session(req.session_id)
        job = require_session_job(session, req.job_id)
        check_email_column(job, req.email_column)
        only = set(req.only_indices) if req.only_indices is not None else None
        plan = plan_recipients(job, req.email_column, req.resend, only)
        sample = None
        first = next((p for p in plan if p["status"] == "ready"), None)
        if first:
            result = next(r for r in job.results if r.index == first["index"])
            values = template_values(result, first["emails"], session.email_settings)
            name = Path(result.pdf or result.png or "Certificate").stem + ".pdf"
            sample = {"row_number": first["row_number"], "to": first["emails"], "attachment": name,
                      "subject": " ".join(render_template(req.subject, values).split()),
                      "body": render_template(req.body, values)}
        return {"counts": summarize(plan), "recipients": plan, "sample": sample,
                "max_per_batch": settings.email_max_per_batch}

    @router.post("/email/test")
    def email_test(req: EmailTestRequest):
        session = require_session(req.session_id)
        smtp = require_smtp(session)
        job = require_session_job(session, req.job_id)
        check_email_column(job, req.email_column)
        valid, invalid = parse_email_list(req.to)
        if len(valid) != 1 or invalid:
            raise HTTPException(422, "Enter one valid address for the test e-mail.")
        plan = plan_recipients(job, req.email_column, resend=True)
        entry = next((p for p in plan if p["status"] == "ready"), None)
        result = next((r for r in job.results if r.index == entry["index"]), None) if entry else \
            next((r for r in job.results if r.status == "generated"), None)
        if result is None:
            raise HTTPException(409, "There is no generated certificate to attach.")
        values = template_values(result, entry["emails"] if entry else [], smtp)
        attachment, filename = certificate_pdf(job, result)
        message = build_message(smtp, valid, "[TEST] " + render_template(req.subject, values),
                                render_template(req.body, values), attachment, filename)
        try:
            conn = open_connection(smtp)
            try:
                conn.send_message(message)
            finally:
                conn.quit()
        except Exception as exc:
            raise HTTPException(502, f"Test e-mail failed: {describe_smtp_error(exc)}") from exc
        return {"sent_to": valid[0], "row_number": result.row_number, "attachment": filename}

    @router.post("/email/send", status_code=202)
    def email_send(req: EmailSendRequest):
        session = require_session(req.session_id)
        smtp = require_smtp(session)
        job = require_session_job(session, req.job_id)
        check_email_column(job, req.email_column)
        if not req.authorized:
            raise HTTPException(400, "Please confirm that you are authorised to e-mail these students.")
        only = set(req.only_indices) if req.only_indices is not None else None
        plan = plan_recipients(job, req.email_column, req.resend, only)
        ready = sum(1 for p in plan if p["status"] == "ready")
        if ready == 0:
            raise HTTPException(409, "There are no e-mails to send.")
        if req.confirm_count != ready:
            raise HTTPException(400, f"Confirmation mismatch: {ready} e-mail(s) would be sent, but {req.confirm_count} was confirmed. "
                                     "Review the recipient list again.")
        if ready > settings.email_max_per_batch:
            raise HTTPException(400, f"{ready} e-mails exceed the batch limit of {settings.email_max_per_batch} "
                                     "(EMAIL_MAX_PER_BATCH). Send in smaller groups.")
        with session.lock:
            for existing_id in session.email_job_ids:
                existing = store.get_email_job(existing_id)
                if existing and existing.is_active:
                    raise HTTPException(409, "E-mails are already being sent for this session.")
            email_job = EmailJob(id=new_id(), session_id=session.id, job_id=job.id, subject=req.subject, body=req.body)
            store.add_email_job(session, email_job)
        threading.Thread(target=run_email_job, name=f"email-{email_job.id[:8]}", daemon=True,
                         args=(email_job, job, smtp, plan, settings.email_delay_seconds)).start()
        return {"email_job_id": email_job.id, "to_send": ready}

    @router.get("/email/jobs/{email_job_id}")
    def email_job_status(email_job_id: str):
        email_job = store.get_email_job(email_job_id)
        if email_job is None:
            raise HTTPException(404, "E-mail job not found or expired.")
        return email_job.snapshot()

    @router.post("/email/jobs/{email_job_id}/cancel")
    def cancel_email_job(email_job_id: str):
        email_job = store.get_email_job(email_job_id)
        if email_job is None:
            raise HTTPException(404, "E-mail job not found or expired.")
        if email_job.is_active:
            email_job.cancel_event.set()
        return {"status": email_job.status, "cancel_requested": email_job.cancel_event.is_set()}

    app.include_router(router)

    # Production: serve the built React app (frontend/dist) from the same origin as the API.
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()

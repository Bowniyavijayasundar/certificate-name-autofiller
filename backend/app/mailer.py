"""Optional e-mail delivery of generated certificates (one PDF per student) over SMTP.

Safety rules:
* Nothing is sent unless the user configured and verified an SMTP account, reviewed the
  recipient list and explicitly confirmed the exact number of e-mails to send.
* Each message goes only to the address(es) in that student's own Excel row and carries
  only that student's certificate.
* A student who was already e-mailed for a job is never e-mailed again unless "resend" is
  explicitly requested. Passwords live in memory only and are never logged or returned.
"""

from __future__ import annotations

import csv
import html
import io
import logging
import smtplib
import ssl
import threading
import time
from dataclasses import asdict, dataclass, field
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from PIL import Image

from .excel_parser import parse_email_list
from .renderer import pdf_bytes

if TYPE_CHECKING:
    from .jobs import CertificateResult, Job

log = logging.getLogger(__name__)

# Patched by tests to avoid real network connections.
SMTP_CLASS = smtplib.SMTP
SMTP_SSL_CLASS = smtplib.SMTP_SSL

PRESETS: dict[str, dict[str, Any]] = {
    "gmail": {
        "label": "Gmail / Google Workspace", "host": "smtp.gmail.com", "port": 465, "security": "ssl",
        "help": "Turn on 2-Step Verification, then create an App Password (Google Account → Security → App passwords) "
                "and use it here. Your normal Gmail password will not work. Personal accounts can send to about 500 recipients a day.",
    },
    "office365": {
        "label": "Microsoft 365 / Outlook (work or school)", "host": "smtp.office365.com", "port": 587, "security": "starttls",
        "help": "Your administrator must allow 'Authenticated SMTP' for the mailbox. Accounts that require "
                "modern (OAuth) sign-in only cannot use this; use your institution's SMTP relay or Gmail instead.",
    },
    "outlook": {
        "label": "Outlook.com / Hotmail (personal)", "host": "smtp-mail.outlook.com", "port": 587, "security": "starttls",
        "help": "Microsoft is phasing out password sign-in for personal accounts; if verification fails, use another provider.",
    },
    "yahoo": {
        "label": "Yahoo Mail", "host": "smtp.mail.yahoo.com", "port": 465, "security": "ssl",
        "help": "Generate an app password in Yahoo Account Security and use it here.",
    },
    "custom": {
        "label": "Other SMTP server (college / company)", "host": "", "port": 587, "security": "starttls",
        "help": "Ask your IT department for the SMTP host, port and security type.",
    },
}

PLACEHOLDERS = ("name", "department", "email", "row", "sender_name")

DEFAULT_SUBJECT = "Your certificate, {name}"
DEFAULT_BODY = (
    "Dear {name},\n\n"
    "Congratulations! Please find your certificate attached to this e-mail as a PDF.\n\n"
    "Best regards,\n{sender_name}"
)

# Server replies that mean "stop sending entirely" (rate limits, quotas, policy blocks).
_ABORT_HINTS = ("quota", "limit", "too many", "rate", "suspended", "blocked", "daily")


class EmailError(ValueError):
    """User-facing problem with the e-mail configuration or request."""


@dataclass
class SmtpSettings:
    host: str
    port: int
    security: str            # ssl | starttls | none
    username: str
    password: str
    from_email: str
    from_name: str = ""
    reply_to: str = ""
    source: str = "session"  # session | server

    def public(self) -> dict:
        return {
            "host": self.host, "port": self.port, "security": self.security, "username": self.username,
            "from_email": self.from_email, "from_name": self.from_name, "reply_to": self.reply_to,
            "password_set": bool(self.password), "source": self.source,
        }


def validate_settings(s: SmtpSettings) -> None:
    if not s.host or any(c in s.host for c in " /\\@"):
        raise EmailError("Enter a valid SMTP host name.")
    if not 1 <= s.port <= 65535:
        raise EmailError("SMTP port must be between 1 and 65535.")
    if s.security not in ("ssl", "starttls", "none"):
        raise EmailError("Security must be ssl, starttls or none.")
    if s.security == "none" and s.password and s.host not in ("localhost", "127.0.0.1", "::1"):
        raise EmailError("Refusing to send a password over an unencrypted connection. Choose SSL or STARTTLS.")
    valid, invalid = parse_email_list(s.from_email)
    if len(valid) != 1 or invalid:
        raise EmailError("Enter one valid sender e-mail address.")
    if s.reply_to:
        valid, invalid = parse_email_list(s.reply_to)
        if len(valid) != 1 or invalid:
            raise EmailError("Reply-to must be one valid e-mail address.")
    if any(c in s.from_name for c in "\r\n"):
        raise EmailError("Sender name cannot contain line breaks.")


def open_connection(s: SmtpSettings, timeout: float = 30) -> smtplib.SMTP:
    context = ssl.create_default_context()
    if s.security == "ssl":
        conn = SMTP_SSL_CLASS(s.host, s.port, timeout=timeout, context=context)
    else:
        conn = SMTP_CLASS(s.host, s.port, timeout=timeout)
        conn.ehlo()
        if s.security == "starttls":
            conn.starttls(context=context)
            conn.ehlo()
    try:
        if s.username:
            conn.login(s.username, s.password)
    except Exception:
        _quit(conn)
        raise
    return conn


def _quit(conn: Optional[smtplib.SMTP]) -> None:
    if conn is None:
        return
    try:
        conn.quit()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def describe_smtp_error(exc: Exception) -> str:
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return ("The mail server rejected the username or password. For Gmail/Yahoo you must use an App Password, "
                "not your normal password.")
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return "The server does not support the selected security/login method. Check the port and security type."
    if isinstance(exc, smtplib.SMTPResponseException):
        message = exc.smtp_error.decode(errors="replace") if isinstance(exc.smtp_error, bytes) else str(exc.smtp_error)
        return f"Mail server error {exc.smtp_code}: {message}"
    if isinstance(exc, (ssl.SSLError, smtplib.SMTPServerDisconnected)):
        return f"Secure connection failed ({exc}). Check that the port matches the security type (465 = SSL, 587 = STARTTLS)."
    if isinstance(exc, OSError):
        return f"Could not connect to the mail server: {exc.strerror or exc}"
    return str(exc) or exc.__class__.__name__


def verify_settings(s: SmtpSettings) -> None:
    validate_settings(s)
    try:
        conn = open_connection(s, timeout=20)
    except Exception as exc:
        raise EmailError(describe_smtp_error(exc)) from exc
    _quit(conn)


# --------------------------------------------------------------------------- composing

def render_template(template: str, values: dict[str, str]) -> str:
    """Replace {placeholders}; unknown braces are left as typed (no str.format surprises)."""
    out = template
    for key in PLACEHOLDERS:
        out = out.replace("{" + key + "}", values.get(key, ""))
    return out


def template_values(result: "CertificateResult", emails: list[str], settings: Optional[SmtpSettings]) -> dict[str, str]:
    return {
        "name": result.name,
        "department": result.department,
        "email": ", ".join(emails),
        "row": str(result.row_number),
        "sender_name": (settings.from_name or settings.from_email) if settings else "",
    }


def build_message(s: SmtpSettings, to: list[str], subject: str, body: str,
                  attachment: Optional[bytes], attachment_name: str) -> EmailMessage:
    subject = " ".join(subject.split())  # strips CR/LF: no header injection
    msg = EmailMessage()
    msg["Subject"] = subject
    local, _, domain = s.from_email.partition("@")
    msg["From"] = Address(display_name=s.from_name, username=local, domain=domain)
    msg["To"] = ", ".join(to)
    if s.reply_to:
        msg["Reply-To"] = s.reply_to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=domain or None)
    msg.set_content(body)
    escaped = html.escape(body).replace("\n", "<br>\n")
    msg.add_alternative(
        f'<div style="font-family:Segoe UI,Arial,sans-serif;font-size:15px;line-height:1.5;color:#1f2937">{escaped}</div>',
        subtype="html",
    )
    if attachment is not None:
        msg.add_attachment(attachment, maintype="application", subtype="pdf", filename=attachment_name)
    return msg


def certificate_pdf(job: "Job", result: "CertificateResult") -> tuple[bytes, str]:
    """The student's own certificate as PDF bytes (re-uses the generated PDF when available)."""
    stem = Path(result.pdf or result.png or "Certificate").stem
    if result.pdf and result.pdf in job.files:
        return job.files[result.pdf].read_bytes(), f"{stem}.pdf"
    if not result.png or result.png not in job.files:
        raise EmailError(f"No certificate file exists for row {result.row_number}.")
    cache = job.dir / "email_pdf" / f"{stem}.pdf"
    if not cache.is_file():
        cache.parent.mkdir(exist_ok=True)
        with Image.open(job.files[result.png]) as image:
            image.load()
            dpi = image.info.get("dpi")
            cache.write_bytes(pdf_bytes(image, tuple(round(float(d)) for d in dpi) if dpi else None))
    return cache.read_bytes(), f"{stem}.pdf"


# --------------------------------------------------------------------------- recipients

def plan_recipients(job: "Job", email_column: str, resend: bool = False,
                    only_indices: Optional[set[int]] = None) -> list[dict]:
    """One entry per Excel row of the job, saying whether (and to whom) it would be sent."""
    plan = []
    for result in job.results:
        record = job.records[result.index] if result.index < len(job.records) else None
        cell = record.values.get(email_column, "") if record else ""
        valid, invalid = parse_email_list(cell)
        entry = {"index": result.index, "row_number": result.row_number, "name": result.name,
                 "emails": valid, "raw_email": cell, "status": "ready", "reason": ""}
        previous = job.email_sent.get(result.index)
        if only_indices is not None and result.index not in only_indices:
            entry["status"], entry["reason"] = "not_selected", "Not part of this send."
        elif result.status != "generated":
            entry["status"], entry["reason"] = "no_certificate", f"No certificate ({result.status})."
        elif not cell:
            entry["status"], entry["reason"] = "no_email", "No e-mail address in this row."
        elif invalid or not valid:
            entry["status"], entry["reason"] = "invalid_email", f"Invalid address: {', '.join(invalid) or cell}"
        elif previous and not resend:
            entry["status"], entry["reason"] = "already_sent", f"Already sent to {', '.join(previous['to'])}."
        plan.append(entry)

    ready = [p for p in plan if p["status"] == "ready"]
    seen: dict[str, list[int]] = {}
    for p in ready:
        for address in p["emails"]:
            seen.setdefault(address.casefold(), []).append(p["row_number"])
    for p in ready:
        shared = sorted({r for a in p["emails"] for r in seen[a.casefold()]} - {p["row_number"]})
        if shared:
            p["reason"] = f"Same address as row(s) {', '.join(map(str, shared))}; each gets their own certificate."
    return plan


def summarize(plan: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in plan:
        counts[p["status"]] = counts.get(p["status"], 0) + 1
    return counts


# --------------------------------------------------------------------------- sending job

@dataclass
class EmailResult:
    index: int
    row_number: int
    name: str
    to: list[str]
    status: str = "pending"      # pending | sent | failed | skipped | cancelled
    message: str = ""
    sent_at: Optional[float] = None


@dataclass
class EmailJob:
    id: str
    session_id: str
    job_id: str
    subject: str
    body: str
    total: int = 0
    status: str = "queued"       # queued | running | completed | cancelled | failed
    processed: int = 0
    results: list[EmailResult] = field(default_factory=list)
    error: Optional[str] = None
    report_path: Optional[Path] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def is_active(self) -> bool:
        return self.status in ("queued", "running")

    def snapshot(self) -> dict:
        with self.lock:
            counts = {s: 0 for s in ("pending", "sent", "failed", "skipped", "cancelled")}
            for r in self.results:
                counts[r.status] += 1
            end = self.finished_at or time.time()
            return {
                "email_job_id": self.id, "job_id": self.job_id, "status": self.status, "total": self.total,
                "processed": self.processed, "counts": counts, "error": self.error,
                "report_file": self.report_path.name if self.report_path and self.report_path.is_file() else None,
                "elapsed_seconds": round(end - self.started_at, 1) if self.started_at else 0,
                "results": [asdict(r) for r in self.results],
            }


def _is_fatal(exc: Exception) -> bool:
    if isinstance(exc, (smtplib.SMTPAuthenticationError, smtplib.SMTPSenderRefused)):
        return True
    if isinstance(exc, smtplib.SMTPResponseException):
        text = (exc.smtp_error.decode(errors="replace") if isinstance(exc.smtp_error, bytes) else str(exc.smtp_error)).lower()
        return exc.smtp_code == 421 or any(h in text for h in _ABORT_HINTS)
    return False


def _write_report(ej: EmailJob, path: Path) -> None:
    def safe(value: str) -> str:
        return f"'{value}" if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Excel Row", "Student Name", "Sent To", "Status", "Sent At", "Message"])
    for r in ej.results:
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.sent_at)) if r.sent_at else ""
        writer.writerow([r.row_number, safe(r.name), "; ".join(r.to), r.status, when, safe(r.message)])
    path.write_text(buffer.getvalue(), encoding="utf-8-sig")


def run_email_job(ej: EmailJob, job: "Job", settings: SmtpSettings, plan: list[dict], delay: float) -> None:
    """Background thread: sends sequentially over one SMTP connection, throttled."""
    ej.status, ej.started_at = "running", time.time()
    results_by_index = {r.index: r for r in job.results}
    conn: Optional[smtplib.SMTP] = None
    consecutive_errors = 0
    try:
        for entry in plan:
            ej.results.append(EmailResult(entry["index"], entry["row_number"], entry["name"], entry["emails"],
                                          "pending" if entry["status"] == "ready" else "skipped", entry["reason"]))
        ej.total = len(ej.results)
        ej.processed = sum(1 for r in ej.results if r.status == "skipped")

        pending = [r for r in ej.results if r.status == "pending"]
        for i, res in enumerate(pending):
            if ej.cancel_event.is_set():
                for rest in pending[i:]:
                    rest.status, rest.message = "cancelled", "Sending was cancelled before this e-mail."
                break
            result = results_by_index[res.index]
            values = template_values(result, res.to, settings)
            try:
                attachment, filename = certificate_pdf(job, result)
                message = build_message(settings, res.to, render_template(ej.subject, values),
                                        render_template(ej.body, values), attachment, filename)
                if conn is None:
                    conn = open_connection(settings)
                try:
                    conn.send_message(message)
                except smtplib.SMTPServerDisconnected:  # idle timeout: reconnect once
                    _quit(conn)
                    conn = open_connection(settings)
                    conn.send_message(message)
                res.status, res.sent_at, res.message = "sent", time.time(), res.message
                job.email_sent[res.index] = {"to": res.to, "at": res.sent_at, "email_job_id": ej.id}
                consecutive_errors = 0
            except EmailError as exc:
                res.status, res.message = "failed", str(exc)
            except smtplib.SMTPRecipientsRefused:
                res.status, res.message = "failed", "The mail server rejected this recipient address."
            except Exception as exc:
                res.status, res.message = "failed", describe_smtp_error(exc)
                consecutive_errors += 1
                _quit(conn)
                conn = None
                if _is_fatal(exc) or consecutive_errors >= 3:
                    ej.error = f"Sending stopped: {describe_smtp_error(exc)}"
                    for rest in pending[i + 1:]:
                        rest.status, rest.message = "failed", "Not sent because sending stopped (see error above)."
                    with ej.lock:
                        ej.processed += 1 + len(pending[i + 1:])
                    break
            with ej.lock:
                ej.processed += 1
            if i < len(pending) - 1 and delay:
                ej.cancel_event.wait(delay)
        ej.status = "cancelled" if ej.cancel_event.is_set() else ("failed" if ej.error else "completed")
    except Exception as exc:  # unexpected: never leave rows silently pending
        log.exception("E-mail job %s failed", ej.id)
        ej.error, ej.status = str(exc) or exc.__class__.__name__, "failed"
        for r in ej.results:
            if r.status == "pending":
                r.status, r.message = "failed", "Not sent because the e-mail job stopped."
    finally:
        _quit(conn)
        try:
            report = job.dir / f"email_report_{ej.id[:8]}.csv"
            _write_report(ej, report)
            ej.report_path = report
            job.files[report.name] = report
        except OSError:
            log.exception("Could not write the e-mail report")
        ej.processed = ej.total
        ej.finished_at = time.time()

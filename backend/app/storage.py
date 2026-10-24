"""Session/job storage on local disk with automatic retention-based cleanup.

All paths are generated server-side from random hex IDs and fixed file names; user supplied
file names are only ever used for display or after strict sanitisation.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .excel_parser import ParsedSheet
from .fonts import FontEntry

if TYPE_CHECKING:
    from .jobs import Job

log = logging.getLogger(__name__)

ID_RE = re.compile(r"^[0-9a-f]{32}$")
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10)),
}


def long_path(path: Path) -> Path:
    """On Windows, use the \\\\?\\ form so paths longer than 260 characters still work
    (deep install folders + long student names). No-op elsewhere."""
    if os.name != "nt":
        return path
    text = str(path.resolve())
    if text.startswith("\\\\?\\"):
        return Path(text)
    if text.startswith("\\\\"):  # UNC share: \\server\share -> \\?\UNC\server\share
        return Path("\\\\?\\UNC\\" + text[2:])
    return Path("\\\\?\\" + text)


def new_id() -> str:
    return uuid.uuid4().hex


def is_valid_id(value: str) -> bool:
    return bool(ID_RE.match(value or ""))


def safe_display_name(name: Optional[str], limit: int = 120) -> str:
    """Original upload name, reduced to its base name, for display only."""
    base = (name or "").replace("\\", "/").split("/")[-1]
    base = _FORBIDDEN.sub("", base).strip()
    return base[:limit] or "upload"


def safe_filename_stem(text: str, limit: int = 80) -> str:
    """Turn a student name into a safe file name stem, keeping letters from any script."""
    text = unicodedata.normalize("NFC", text)
    text = _FORBIDDEN.sub("", text)
    # Keep letters, combining marks (needed by Indic scripts) and digits; drop symbols/emoji.
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] in "LMN" or ch in " _.'-")
    text = re.sub(r"[\s]+", "_", text.strip())
    text = re.sub(r"_+", "_", text).strip("._- ")
    text = text[:limit].rstrip("._- ")
    if text.lower().split(".")[0] in _WINDOWS_RESERVED:
        text = f"_{text}"
    return text


class UniqueNamer:
    """Allocates collision-free file names (case-insensitive, as on Windows/macOS)."""

    def __init__(self) -> None:
        self._used: set[str] = set()

    def allocate(self, stem: str, suffix: str = "_Certificate") -> str:
        candidate = f"{stem}{suffix}"
        n = 2
        while candidate.casefold() in self._used:
            candidate = f"{stem}_{n}{suffix}"
            n += 1
        self._used.add(candidate.casefold())
        return candidate


@dataclass
class Session:
    id: str
    dir: Path
    created_at: float = field(default_factory=time.time)
    last_access: float = field(default_factory=time.time)
    excel_path: Optional[Path] = None
    excel_filename: Optional[str] = None
    parsed: Optional[ParsedSheet] = None
    template_path: Optional[Path] = None
    template_info: Optional[dict[str, Any]] = None
    template_cache: Optional[Any] = None          # decoded renderer.Template for fast previews
    fonts: dict[str, FontEntry] = field(default_factory=dict)
    job_ids: list[str] = field(default_factory=list)
    email_settings: Optional[Any] = None          # mailer.SmtpSettings; memory only, never written to disk
    email_job_ids: list[str] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def touch(self) -> None:
        self.last_access = time.time()


class SessionStore:
    def __init__(self, root: Path, retention_seconds: float):
        self.root = long_path(root)
        self.retention_seconds = retention_seconds
        self._sessions: dict[str, Session] = {}
        self._jobs: dict[str, "Job"] = {}
        self._email_jobs: dict[str, Any] = {}
        self._lock = threading.Lock()

    # -- lifecycle -------------------------------------------------------------------------
    def initialise(self) -> None:
        """Create the storage folder and remove leftovers from a previous run (their
        in-memory metadata is gone, so they could never be downloaded or cleaned otherwise)."""
        self.root.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.root, 0o700)  # shared /tmp on Linux/macOS: only this user may read student data
        for child in self.root.iterdir():
            if child.is_dir() and is_valid_id(child.name):
                shutil.rmtree(child, ignore_errors=True)

    def create(self) -> Session:
        session_id = new_id()
        directory = self.root / session_id
        directory.mkdir(parents=True)
        session = Session(id=session_id, dir=directory)
        with self._lock:
            self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Optional[Session]:
        if not is_valid_id(session_id):
            return None
        with self._lock:
            session = self._sessions.get(session_id)
        if session:
            session.touch()
        return session

    def delete(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session:
                for job_id in session.job_ids + session.email_job_ids:
                    job = self._jobs.pop(job_id, None) or self._email_jobs.pop(job_id, None)
                    if job:
                        job.cancel_event.set()
                session.email_settings = None
        if session:
            shutil.rmtree(session.dir, ignore_errors=True)
        return session is not None

    # -- jobs ------------------------------------------------------------------------------
    def add_job(self, session: Session, job: "Job") -> None:
        with self._lock:
            self._jobs[job.id] = job
            session.job_ids.append(job.id)

    def get_job(self, job_id: str) -> Optional["Job"]:
        if not is_valid_id(job_id):
            return None
        with self._lock:
            job = self._jobs.get(job_id)
            session = self._sessions.get(job.session_id) if job else None
        if session:
            session.touch()
        return job

    def add_email_job(self, session: Session, email_job: Any) -> None:
        with self._lock:
            self._email_jobs[email_job.id] = email_job
            session.email_job_ids.append(email_job.id)

    def get_email_job(self, email_job_id: str) -> Optional[Any]:
        if not is_valid_id(email_job_id):
            return None
        with self._lock:
            email_job = self._email_jobs.get(email_job_id)
            session = self._sessions.get(email_job.session_id) if email_job else None
        if session:
            session.touch()
        return email_job

    # -- retention -------------------------------------------------------------------------
    def _busy(self, session: Session) -> bool:
        jobs = [self._jobs.get(j) for j in session.job_ids] + [self._email_jobs.get(j) for j in session.email_job_ids]
        return any(j is not None and j.is_active for j in jobs)

    def cleanup_expired(self, now: Optional[float] = None) -> int:
        now = now or time.time()
        with self._lock:
            expired = [
                s.id for s in self._sessions.values()
                if now - s.last_access > self.retention_seconds and not self._busy(s)
            ]
        for session_id in expired:
            self.delete(session_id)
        if expired:
            log.info("Retention cleanup removed %d expired session(s)", len(expired))
        return len(expired)

    def clear_all(self) -> None:
        with self._lock:
            ids = list(self._sessions)
        for session_id in ids:
            self.delete(session_id)


class CleanupThread(threading.Thread):
    def __init__(self, store: SessionStore, interval_seconds: float):
        super().__init__(name="retention-cleanup", daemon=True)
        self.store = store
        self.interval = interval_seconds
        self.stop_event = threading.Event()

    def run(self) -> None:
        while not self.stop_event.wait(self.interval):
            try:
                self.store.cleanup_expired()
            except Exception:  # never let the cleanup thread die
                log.exception("Retention cleanup failed")

    def stop(self) -> None:
        self.stop_event.set()

"""Application settings loaded from environment variables (and an optional backend/.env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")


def _int_env(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise RuntimeError(f"Environment variable {name} must be >= {minimum}, got {value}")
    return value


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be a number, got {raw!r}") from exc
    if value < 0:
        raise RuntimeError(f"Environment variable {name} must be >= 0, got {value}")
    return value


@dataclass(frozen=True)
class Settings:
    storage_dir: Path
    retention_minutes: int = 60
    cleanup_interval_seconds: int = 300
    max_excel_mb: int = 10
    max_template_mb: int = 30
    max_font_mb: int = 10
    max_rows: int = 5000
    max_template_pixels: int = 80_000_000
    max_workers: int = 4
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])
    # Optional server-side SMTP account (otherwise the user enters it in the app).
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_security: str = "ssl"          # ssl | starttls | none
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = ""
    email_delay_seconds: float = 1.0    # pause between messages (provider rate limits)
    email_max_per_batch: int = 500     # Gmail personal accounts allow ~500 recipients/day

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from_email)

    @property
    def sessions_dir(self) -> Path:
        return self.storage_dir / "sessions"


def load_settings() -> Settings:
    storage = os.getenv("STORAGE_DIR", "").strip()
    storage_dir = Path(storage) if storage else BACKEND_DIR / "storage"
    if not storage_dir.is_absolute():
        storage_dir = (BACKEND_DIR / storage_dir).resolve()

    origins_raw = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    origins = [o.strip() for o in origins_raw.split(",") if o.strip()]

    return Settings(
        storage_dir=storage_dir,
        retention_minutes=_int_env("RETENTION_MINUTES", 60, minimum=1),
        cleanup_interval_seconds=_int_env("CLEANUP_INTERVAL_SECONDS", 300, minimum=10),
        max_excel_mb=_int_env("MAX_EXCEL_MB", 10, minimum=1),
        max_template_mb=_int_env("MAX_TEMPLATE_MB", 30, minimum=1),
        max_font_mb=_int_env("MAX_FONT_MB", 10, minimum=1),
        max_rows=_int_env("MAX_ROWS", 5000, minimum=1),
        max_template_pixels=_int_env("MAX_TEMPLATE_PIXELS", 80_000_000, minimum=1),
        max_workers=_int_env("MAX_WORKERS", min(4, os.cpu_count() or 1), minimum=1),
        cors_origins=origins,
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_port=_int_env("SMTP_PORT", 465, minimum=1),
        smtp_security=os.getenv("SMTP_SECURITY", "ssl").strip().lower() or "ssl",
        smtp_username=os.getenv("SMTP_USERNAME", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from_email=os.getenv("SMTP_FROM_EMAIL", "").strip(),
        smtp_from_name=os.getenv("SMTP_FROM_NAME", "").strip(),
        email_delay_seconds=_float_env("EMAIL_DELAY_SECONDS", 1.0),
        email_max_per_batch=_int_env("EMAIL_MAX_PER_BATCH", 500, minimum=1),
    )

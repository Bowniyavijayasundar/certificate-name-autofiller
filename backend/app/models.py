"""Pydantic request/response schemas shared by the API."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

ID_PATTERN = r"^[0-9a-f]{32}$"


class Box(BaseModel):
    """Text area in ORIGINAL template pixels (independent of on-screen zoom)."""

    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class TextStyle(BaseModel):
    box: Box
    font_id: str = Field(min_length=1, max_length=200)
    font_size: int = Field(ge=4, le=2000, description="Preferred (maximum) font size in pixels")
    min_font_size: int = Field(ge=4, le=2000, description="Smallest size auto-fit may shrink to")
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    align: Literal["left", "center", "right"] = "center"
    vertical_align: Literal["top", "middle", "bottom"] = "middle"
    allow_wrap: bool = True
    max_lines: int = Field(default=2, ge=1, le=5)
    line_spacing: float = Field(default=1.15, ge=0.8, le=3.0)

    @model_validator(mode="after")
    def _check_sizes(self) -> "TextStyle":
        if self.min_font_size > self.font_size:
            raise ValueError("min_font_size cannot be larger than font_size")
        return self


class ColumnMapping(BaseModel):
    name_column: str = Field(min_length=1)
    department_column: Optional[str] = None
    email_column: Optional[str] = None


class CertificateConfig(BaseModel):
    mapping: ColumnMapping
    name: TextStyle
    department_enabled: bool = False
    department: Optional[TextStyle] = None

    @model_validator(mode="after")
    def _check_department(self) -> "CertificateConfig":
        if self.department_enabled:
            if self.department is None:
                raise ValueError("department style is required when department text is enabled")
            if not self.mapping.department_column:
                raise ValueError("select a department column to print department text")
        return self


class SessionRef(BaseModel):
    session_id: str = Field(pattern=ID_PATTERN)


class ReparseRequest(SessionRef):
    sheet: Optional[str] = None
    header_row: str = Field(default="auto", description='"auto", "none" or a 1-based row number')


class AnalyzeRequest(SessionRef):
    mapping: ColumnMapping


class PreviewRequest(SessionRef):
    record_index: int = Field(ge=0)
    config: CertificateConfig
    max_width: int = Field(default=1600, ge=200, le=10000)


class ValidateRequest(SessionRef):
    config: CertificateConfig


class OutputFormats(BaseModel):
    png: bool = True
    pdf: bool = False

    @model_validator(mode="after")
    def _at_least_one(self) -> "OutputFormats":
        if not (self.png or self.pdf):
            raise ValueError("choose at least one output format")
        return self


class SmtpConfigRequest(SessionRef):
    use_server_config: bool = Field(default=False, description="Use the SMTP account from the server's .env")
    preset: Literal["gmail", "office365", "outlook", "yahoo", "custom"] = "custom"
    host: str = Field(default="", max_length=253)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    security: Optional[Literal["ssl", "starttls", "none"]] = None
    username: str = Field(default="", max_length=254)
    password: str = Field(default="", max_length=512)
    from_email: str = Field(default="", max_length=254)
    from_name: str = Field(default="", max_length=100)
    reply_to: str = Field(default="", max_length=254)


class EmailCompose(SessionRef):
    job_id: str = Field(pattern=ID_PATTERN)
    email_column: str = Field(min_length=1)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)


class EmailPreviewRequest(EmailCompose):
    resend: bool = False
    only_indices: Optional[list[int]] = None


class EmailTestRequest(EmailCompose):
    to: str = Field(min_length=3, max_length=254, description="Where to send the test (usually yourself)")


class EmailSendRequest(EmailCompose):
    resend: bool = Field(default=False, description="Also e-mail students who were already sent their certificate")
    only_indices: Optional[list[int]] = Field(default=None, description="Restrict to these records (e.g. retry failed)")
    authorized: bool = Field(description="User confirmed they are authorised to e-mail these students")
    confirm_count: int = Field(ge=0, description="Must equal the number of e-mails that will be sent")


class GenerateRequest(SessionRef):
    config: CertificateConfig
    formats: OutputFormats = OutputFormats()
    approved: bool = Field(description="User confirmed they reviewed and approved the preview")

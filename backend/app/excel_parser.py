"""Excel (.xlsx / .xls) parsing: header detection, cell cleaning and record analysis.

Rules:
* Every data row keeps its original Excel row number so certificates map 1:1 to rows.
* Names keep their original spelling and capitalization; only surrounding/duplicate
  whitespace and invisible junk characters are removed.
* Literal strings such as "NA" or "None" are kept as text, never turned into blanks.
"""

from __future__ import annotations

import datetime as dt
import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pandas as pd

XLSX_MAGIC = b"PK\x03\x04"
XLS_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

HEADER_SCAN_ROWS = 10

# Zero-width / BOM characters that are never meaningful in a name. ZWJ (U+200D) and
# ZWNJ (U+200C) are deliberately NOT removed: they matter in Indic and Arabic scripts.
_INVISIBLE = dict.fromkeys(map(ord, "​⁠﻿­"), None)
_WHITESPACE_RUN = re.compile(r"\s+")

FIELDS = ("name", "department", "email")

_EXACT_SYNONYMS: dict[str, set[str]] = {
    "name": {
        "student name", "name", "full name", "participant name", "candidate name", "student",
        "name of the student", "name of student", "student full name", "participant", "candidate",
        "recipient name", "recipient", "awardee name", "trainee name", "attendee name", "names",
        "students name", "student's name",
    },
    "department": {
        "department", "dept", "department name", "branch", "course", "programme", "program",
        "discipline", "stream", "class", "dept name", "faculty", "division",
    },
    "email": {
        "email", "e mail", "email address", "e mail address", "mail", "email id", "mail id",
        "student email", "email ids", "emailid", "e mail id",
    },
}

_NAME_EXCLUDE = (
    "father", "mother", "guardian", "parent", "college", "institution", "institute", "school",
    "university", "department", "dept", "course", "event", "company", "organisation",
    "organization", "file", "user", "team", "project", "mentor", "guide", "teacher", "faculty",
)


class ExcelParseError(ValueError):
    """Raised for files that cannot be read as a spreadsheet."""


@dataclass
class StudentRecord:
    index: int          # position among parsed records (0-based, stable)
    row_number: int     # original 1-based Excel row number
    values: dict[str, str]


@dataclass
class ParsedSheet:
    sheets: list[str]
    sheet: str
    header_row_number: Optional[int]   # 1-based row number of the header, None = no header row
    columns: list[str]
    records: list[StudentRecord]
    detected_mapping: dict[str, Optional[str]]
    ignored_empty_rows: int


@dataclass
class RecordAnalysis:
    total_rows: int
    valid_names: int
    blank_name_rows: list[int] = field(default_factory=list)
    duplicate_groups: list[dict[str, Any]] = field(default_factory=list)
    invalid_email_rows: list[int] = field(default_factory=list)
    blank_department_rows: list[int] = field(default_factory=list)


# --------------------------------------------------------------------------- cells

def clean_cell(value: Any) -> str:
    """Convert a raw cell value to clean text while preserving spelling and case."""
    if value is None or value is pd.NaT:
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        text = str(int(value)) if value.is_integer() else repr(value)
    elif isinstance(value, bool):
        text = "TRUE" if value else "FALSE"
    elif isinstance(value, (pd.Timestamp, dt.datetime)):
        text = value.date().isoformat() if (value.hour, value.minute, value.second) == (0, 0, 0) else value.isoformat(sep=" ")
    elif isinstance(value, dt.date):
        text = value.isoformat()
    else:
        text = str(value)

    text = unicodedata.normalize("NFC", text).translate(_INVISIBLE)
    # Drop control characters other than whitespace (which is collapsed next).
    text = "".join(ch for ch in text if ch.isspace() or unicodedata.category(ch) != "Cc")
    return _WHITESPACE_RUN.sub(" ", text).strip()


def _normalize_header(text: str) -> str:
    text = text.casefold().replace("_", " ").replace("-", " ").replace(".", " ")
    text = re.sub(r"[^\w\s']", " ", text)
    return _WHITESPACE_RUN.sub(" ", text).strip()


def match_header(header: str) -> tuple[Optional[str], int]:
    """Return (field, score) for a header cell. Higher score = more confident."""
    norm = _normalize_header(header)
    if not norm:
        return None, 0
    for fld in FIELDS:
        if norm in _EXACT_SYNONYMS[fld]:
            return fld, 3
    tokens = set(norm.split())
    if "email" in norm or "e mail" in norm or tokens & {"mail", "gmail"}:
        return "email", 2
    if tokens & {"department", "dept", "branch", "programme", "program", "course"}:
        return "department", 2
    if "name" in tokens and not any(word in norm for word in _NAME_EXCLUDE):
        strong = tokens & {"student", "students", "participant", "candidate", "full", "recipient", "awardee", "trainee"}
        return "name", 2 if strong else 1
    return None, 0


# --------------------------------------------------------------------------- reading

def detect_engine(path: Path) -> str:
    with path.open("rb") as fh:
        head = fh.read(8)
    if head.startswith(XLSX_MAGIC):
        return "openpyxl"
    if head == XLS_MAGIC:
        # pandas deprecates xlrd; prefer the calamine engine for legacy .xls when installed.
        try:
            import python_calamine  # noqa: F401
            return "calamine"
        except ImportError:
            return "xlrd"
    raise ExcelParseError("The file is not a valid Excel workbook (.xlsx or .xls).")


def list_sheets(path: Path, engine: str) -> list[str]:
    try:
        with pd.ExcelFile(path, engine=engine) as book:
            return [str(name) for name in book.sheet_names]
    except Exception as exc:  # corrupt / password-protected / unsupported files
        raise ExcelParseError(f"Could not open the workbook: {exc}") from exc


def read_matrix(path: Path, engine: str, sheet: str) -> list[list[str]]:
    try:
        frame = pd.read_excel(
            path, sheet_name=sheet, header=None, dtype=object, engine=engine,
            keep_default_na=False, na_filter=False,
        )
    except Exception as exc:
        raise ExcelParseError(f"Could not read sheet {sheet!r}: {exc}") from exc
    return [[clean_cell(v) for v in row] for row in frame.itertuples(index=False, name=None)]


def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _unique_columns(raw_headers: list[str]) -> list[str]:
    columns: list[str] = []
    seen: dict[str, int] = {}
    for i, header in enumerate(raw_headers):
        name = header or f"Column {_column_letter(i)}"
        key = name.casefold()
        if key in seen:
            seen[key] += 1
            name = f"{name} ({seen[key]})"
        else:
            seen[key] = 1
        columns.append(name)
    return columns


def _mapping_for_headers(headers: list[str]) -> tuple[dict[str, Optional[str]], int]:
    best: dict[str, tuple[int, int]] = {}  # field -> (score, column index)
    for i, header in enumerate(headers):
        fld, score = match_header(header)
        if fld and (fld not in best or score > best[fld][0]):
            best[fld] = (score, i)
    mapping = {fld: (headers[best[fld][1]] if fld in best else None) for fld in FIELDS}
    return mapping, sum(score for score, _ in best.values())


def _detect_header_row(matrix: list[list[str]]) -> Optional[int]:
    """Index (0-based) of the most likely header row, or None if nothing looks like one."""
    best_row, best_score = None, 0
    scanned = 0
    for r, row in enumerate(matrix):
        if not any(row):
            continue
        scanned += 1
        if scanned > HEADER_SCAN_ROWS:
            break
        mapping, score = _mapping_for_headers(row)
        if mapping["name"] is None:
            score = score // 2  # a header row without a name column is less convincing
        if score > best_score:
            best_row, best_score = r, score
    return best_row


def _guess_email_column(columns: list[str], records: list[StudentRecord]) -> Optional[str]:
    for col in columns:
        values = [rec.values[col] for rec in records if rec.values[col]]
        if values and sum("@" in v for v in values) / len(values) >= 0.8:
            return col
    return None


def parse_workbook(
    path: Path,
    sheet: Optional[str] = None,
    header_row: Optional[int | str] = "auto",
    max_rows: int = 5000,
) -> ParsedSheet:
    """Parse a workbook.

    header_row: "auto" to detect, "none" when the sheet has no header row, or a 1-based
    row number chosen by the user.
    """
    engine = detect_engine(path)
    sheets = list_sheets(path, engine)
    if not sheets:
        raise ExcelParseError("The workbook does not contain any sheets.")

    matrices: dict[str, list[list[str]]] = {}
    if sheet is None:
        for candidate in sheets:  # default: first sheet that has data
            matrices[candidate] = read_matrix(path, engine, candidate)
            if any(any(row) for row in matrices[candidate]):
                sheet = candidate
                break
        else:
            raise ExcelParseError("The workbook is empty: no sheet contains any data.")
    elif sheet not in sheets:
        raise ExcelParseError(f"Sheet {sheet!r} does not exist in this workbook.")

    matrix = matrices.get(sheet) or read_matrix(path, engine, sheet)
    width = max((len(row) for row in matrix), default=0)
    # Trim trailing all-empty columns (common with formatted but unused cells).
    while width and not any(len(row) >= width and row[width - 1] for row in matrix):
        width -= 1
    matrix = [(row + [""] * width)[:width] for row in matrix]
    if width == 0:
        raise ExcelParseError(f"Sheet {sheet!r} is empty.")

    if header_row in (None, "auto"):
        header_idx = _detect_header_row(matrix)
        if header_idx is None:  # nothing recognisable: assume the first non-empty row is the header
            header_idx = next(i for i, row in enumerate(matrix) if any(row))
    elif header_row == "none":
        header_idx = None
    else:
        try:
            header_idx = int(header_row) - 1
        except (TypeError, ValueError) as exc:
            raise ExcelParseError(f"Invalid header row {header_row!r}.") from exc
        if not 0 <= header_idx < len(matrix):
            raise ExcelParseError(f"Header row {header_row} is outside the sheet (1-{len(matrix)}).")

    if header_idx is None:
        columns = [f"Column {_column_letter(i)}" for i in range(width)]
        data_start = 0
    else:
        columns = _unique_columns(matrix[header_idx])
        data_start = header_idx + 1

    records: list[StudentRecord] = []
    for r in range(data_start, len(matrix)):
        row = matrix[r]
        if not any(row):
            continue
        records.append(StudentRecord(index=len(records), row_number=r + 1, values=dict(zip(columns, row))))
        if len(records) > max_rows:
            raise ExcelParseError(f"The sheet has more than {max_rows} data rows (limit set by MAX_ROWS).")

    # Trailing empty rows are just padding, not "ignored" data rows.
    last_data_row = records[-1].row_number if records else data_start
    ignored_empty = sum(1 for r in range(data_start, min(last_data_row, len(matrix))) if not any(matrix[r]))

    mapping, _ = _mapping_for_headers(columns) if header_idx is not None else ({f: None for f in FIELDS}, 0)
    if mapping["email"] is None:
        mapping["email"] = _guess_email_column(columns, records)
        if mapping["email"] in (mapping["name"], mapping["department"]):
            mapping["email"] = None

    return ParsedSheet(
        sheets=sheets,
        sheet=sheet,
        header_row_number=None if header_idx is None else header_idx + 1,
        columns=columns,
        records=records,
        detected_mapping=mapping,
        ignored_empty_rows=ignored_empty,
    )


# --------------------------------------------------------------------------- analysis

_EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$")
_EMAIL_SPLIT = re.compile(r"[;,\s]+")


def parse_email_list(cell: str) -> tuple[list[str], list[str]]:
    """Split a cell such as "a@x.com; b@y.org" into (valid addresses, invalid parts)."""
    valid, invalid = [], []
    for part in _EMAIL_SPLIT.split(cell.strip().strip("<>")):
        part = part.strip().strip("<>").removeprefix("mailto:")
        if not part:
            continue
        (valid if len(part) <= 254 and _EMAIL_RE.match(part) else invalid).append(part)
    return valid, invalid


def analyze_records(
    records: list[StudentRecord],
    name_column: str,
    department_column: Optional[str] = None,
    email_column: Optional[str] = None,
) -> RecordAnalysis:
    analysis = RecordAnalysis(total_rows=len(records), valid_names=0)
    groups: dict[str, list[StudentRecord]] = {}
    for rec in records:
        name = rec.values.get(name_column, "")
        if not name:
            analysis.blank_name_rows.append(rec.row_number)
            continue
        analysis.valid_names += 1
        groups.setdefault(name.casefold(), []).append(rec)
        if department_column and not rec.values.get(department_column, ""):
            analysis.blank_department_rows.append(rec.row_number)
        if email_column:
            email = rec.values.get(email_column, "")
            if email and parse_email_list(email)[1]:
                analysis.invalid_email_rows.append(rec.row_number)
    analysis.duplicate_groups = [
        {"name": recs[0].values[name_column], "rows": [r.row_number for r in recs]}
        for recs in groups.values() if len(recs) > 1
    ]
    return analysis

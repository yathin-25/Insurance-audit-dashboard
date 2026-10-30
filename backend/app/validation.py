"""Safe upload parsing and validation.

Two kinds of problems are handled differently:
  * STRUCTURAL (wrong file type, missing columns, too large, corrupt) -> upload is REJECTED
    with a clear error list.
  * VALUE-LEVEL (a bad date, a negative amount, a blank cell) -> upload is ACCEPTED, the cell
    is recorded in `bad`, and the evaluation reports it as an observation.
"""
import io
import os
import re
import zipfile
from dataclasses import dataclass, field
from typing import List

import numpy as np
import pandas as pd

from .config import Settings

REQUIRED_COLUMNS = [
    "claim_id", "policy_number", "claim_type", "date_reported", "status",
    "claim_amount", "documents_required", "documents_received",
    "policy_check_completed", "sla_days",
]
OPTIONAL_COLUMNS = ["date_closed", "approved_amount", "paid_amount", "adjuster_id"]

STRING_COLS = ["claim_id", "policy_number", "claim_type", "status", "adjuster_id"]
TITLE_COLS = {"claim_type", "status"}
DATE_COLS = ["date_reported", "date_closed"]
NUMERIC_COLS = ["claim_amount", "approved_amount", "paid_amount",
                "documents_required", "documents_received", "sla_days"]
INTEGER_COLS = {"documents_required", "documents_received", "sla_days"}
BOOL_COLS = ["policy_check_completed"]
ALL_COLS = STRING_COLS + DATE_COLS + NUMERIC_COLS + BOOL_COLS

ALLOWED_EXT = {".csv", ".xlsx"}
MAX_STR_LEN = 100
MAX_UNCOMPRESSED = 200 * 1024 * 1024
MAX_ZIP_RATIO = 100
TRUE_VALUES = {"yes", "y", "true", "1"}
FALSE_VALUES = {"no", "n", "false", "0"}


class UploadValidationError(Exception):
    def __init__(self, errors: List[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class ParsedData:
    df: pd.DataFrame
    bad: pd.DataFrame
    row_count: int
    warnings: List[str] = field(default_factory=list)


def sanitize_filename(name: str) -> str:
    base = os.path.basename(name or "").replace("\\", "/").split("/")[-1]
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:100]
    return base or "upload"


def _extension(filename: str) -> str:
    return os.path.splitext(filename.lower())[1]


def _check_content(ext: str, content: bytes) -> None:
    if not content:
        raise UploadValidationError(["The file is empty."])
    if ext == ".xlsx":
        if not content.startswith(b"PK\x03\x04"):
            raise UploadValidationError(["File content is not a valid .xlsx workbook."])
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                infos = zf.infolist()
                total = sum(i.file_size for i in infos)
                if total > MAX_UNCOMPRESSED or total > max(len(content), 1) * MAX_ZIP_RATIO:
                    raise UploadValidationError(["Workbook expands to an unsafe size and was rejected."])
                names = {i.filename for i in infos}
                if "xl/workbook.xml" not in names:
                    raise UploadValidationError(["File content is not a valid .xlsx workbook."])
                if any(n.lower().endswith("vbaproject.bin") for n in names):
                    raise UploadValidationError(["Workbooks containing macros are not accepted."])
        except zipfile.BadZipFile:
            raise UploadValidationError(["File content is not a valid .xlsx workbook."])
    else:
        if b"\x00" in content[:8192]:
            raise UploadValidationError(["File content is binary, not a text CSV."])


def _read_raw(ext: str, content: bytes, max_rows: int) -> pd.DataFrame:
    try:
        if ext == ".csv":
            text = content.decode("utf-8-sig")
            raw = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False,
                              nrows=max_rows + 1, on_bad_lines="error")
        else:
            raw = pd.read_excel(io.BytesIO(content), dtype=str, engine="openpyxl",
                                sheet_name=0, nrows=max_rows + 1)
    except UnicodeDecodeError:
        raise UploadValidationError(["CSV must be UTF-8 encoded."])
    except Exception:  # never leak parser internals to the client
        raise UploadValidationError(["The file could not be read. Check that it is a well-formed CSV/XLSX."])
    return raw


def _clean_cell(v):
    if isinstance(v, str):
        v = v.strip()
        return np.nan if v == "" else v
    return np.nan if v is None else v


def _to_bool(v):
    if not isinstance(v, str):
        return pd.NA, False
    low = v.lower()
    if low in TRUE_VALUES:
        return True, False
    if low in FALSE_VALUES:
        return False, False
    return pd.NA, True


def parse_upload(filename: str, content: bytes, settings: Settings) -> ParsedData:
    ext = _extension(filename)
    if ext not in ALLOWED_EXT:
        raise UploadValidationError([f"Unsupported file type '{ext or 'none'}'. Allowed: .csv, .xlsx"])
    _check_content(ext, content)
    raw = _read_raw(ext, content, settings.max_rows)

    if len(raw) > settings.max_rows:
        raise UploadValidationError([f"File has more than the allowed {settings.max_rows} rows."])

    cols = [str(c).strip().lower().replace(" ", "_") for c in raw.columns]
    if len(set(cols)) != len(cols):
        raise UploadValidationError(["Duplicate column names found in the header."])
    raw.columns = cols

    missing = [c for c in REQUIRED_COLUMNS if c not in cols]
    if missing:
        raise UploadValidationError([f"Missing required column(s): {', '.join(missing)}"])

    warnings = []
    unknown = [c for c in cols if c not in ALL_COLS]
    if unknown:
        warnings.append(f"Ignored unrecognised column(s): {', '.join(unknown[:10])}")

    raw = raw.astype(object)
    for c in raw.columns:
        raw[c] = raw[c].map(_clean_cell)
    raw = raw.dropna(how="all")  # blank rows; original index kept so row numbers stay accurate
    if raw.empty:
        raise UploadValidationError(["The file has a header but no data rows."])

    df = pd.DataFrame(index=raw.index)
    bad = pd.DataFrame(False, index=raw.index, columns=ALL_COLS)
    nan_series = pd.Series(np.nan, index=raw.index, dtype=object)

    for c in STRING_COLS:
        s = raw[c] if c in raw.columns else nan_series
        if c in TITLE_COLS:
            s = s.map(lambda v: v.title() if isinstance(v, str) else v)
        too_long = s.map(lambda v: isinstance(v, str) and len(v) > MAX_STR_LEN)
        bad[c] = too_long.astype(bool)
        df[c] = s.where(~too_long, np.nan)

    for c in DATE_COLS:
        s = raw[c] if c in raw.columns else nan_series
        parsed = pd.to_datetime(s, errors="coerce", format="ISO8601")
        if getattr(parsed.dt, "tz", None) is not None:
            parsed = parsed.dt.tz_convert("UTC").dt.tz_localize(None)
        bad[c] = (s.notna() & parsed.isna()).astype(bool)
        df[c] = parsed.dt.normalize()

    for c in NUMERIC_COLS:
        s = raw[c] if c in raw.columns else nan_series
        num = pd.to_numeric(s, errors="coerce")
        num = num.where(np.isfinite(num), np.nan)
        invalid = s.notna() & num.isna()
        if c in INTEGER_COLS:
            invalid = invalid | (num.notna() & (num % 1 != 0))
            num = num.where(~invalid, np.nan)
        bad[c] = invalid.astype(bool)
        df[c] = num

    for c in BOOL_COLS:
        pairs = raw[c].map(_to_bool)
        df[c] = pairs.map(lambda p: p[0]).astype("boolean")
        bad[c] = pairs.map(lambda p: p[1]).astype(bool)

    return ParsedData(df=df, bad=bad, row_count=len(df), warnings=warnings)

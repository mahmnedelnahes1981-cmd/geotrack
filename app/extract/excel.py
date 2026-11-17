"""Deterministic extractor for Excel/CSV BOQ files (no LLM involved)."""

import csv
import io
from pathlib import Path

from openpyxl import load_workbook

from app.extract.base import ExtractionResult
from app.extract.rows import build_drafts_from_rows, parse_decimal

__all__ = ["extract_file", "parse_decimal"]

_ENCODINGS = ("utf-8-sig", "utf-8", "windows-1256", "windows-1252", "latin-1")


def extract_file(path: str | Path) -> ExtractionResult:
    path = Path(path)
    ext = path.suffix.lower()
    if ext in {".xlsx", ".xlsm"}:
        return _extract_excel(path)
    if ext == ".csv":
        return _extract_csv(path)
    raise ValueError(f"Unsupported spreadsheet type: {ext}")


def _extract_excel(path: Path) -> ExtractionResult:
    result = ExtractionResult(drafts=[])
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        result.sheets = wb.sheetnames
        for ws in wb.worksheets:
            rows = [[c for c in row] for row in ws.iter_rows(values_only=True)]
            build_drafts_from_rows(rows, ws.title, result)
    finally:
        wb.close()
    return result


def _read_csv_text(path: Path) -> str:
    data = path.read_bytes()
    for enc in _ENCODINGS:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _extract_csv(path: Path) -> ExtractionResult:
    result = ExtractionResult(drafts=[])
    text = _read_csv_text(path)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","

    rows = [list(row) for row in csv.reader(io.StringIO(text), delimiter=delimiter)]
    build_drafts_from_rows(rows, path.stem, result)
    result.sheets = [path.stem]
    return result

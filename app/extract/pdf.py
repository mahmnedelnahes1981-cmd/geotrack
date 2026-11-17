"""Digital-PDF BOQ extractor (pdfplumber, deterministic, no LLM).

Handles born-digital PDFs (Word/LibreOffice/exported tables) in AR and EN.

Not handled (explicit warnings, no silent failures):
- scanned/image PDFs with no text layer -> suggests OCR (Azure/Google/Tesseract)
- hand-drawn or heavily merged tables without grid lines (best-effort text-strategy fallback)
- tables split across pages without repeated headers
"""

from pathlib import Path

import pdfplumber

from app.extract.arabic import fix_visual_order_arabic
from app.extract.base import ExtractionResult
from app.extract.rows import build_drafts_from_rows

MIN_TEXT_CHARS = 20
_TEXT_TABLE_SETTINGS = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
    "snap_tolerance": 4,
    "join_tolerance": 4,
    "min_words_vertical": 1,
    "min_words_horizontal": 1,
}


def _clean_cell(cell: object) -> str:
    if cell is None:
        return ""
    return fix_visual_order_arabic(str(cell).replace("\n", " ")).strip()


def extract_pdf(path: str | Path) -> ExtractionResult:
    path = Path(path)
    result = ExtractionResult(drafts=[])

    with pdfplumber.open(path) as pdf:
        page_texts = [(p.extract_text() or "") for p in pdf.pages]
        total_chars = sum(len(t.strip()) for t in page_texts)
        if total_chars < MIN_TEXT_CHARS:
            result.warnings.append(
                "PDF has no usable text layer (scanned image?). "
                "OCR is not implemented yet — route via Azure Document Intelligence, "
                "Google Document AI, or Tesseract before extraction."
            )
            return result

        result.sheets = [f"page {i + 1}" for i in range(len(pdf.pages))]

        for pageno, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables()
            if not tables:
                tables = page.extract_tables(_TEXT_TABLE_SETTINGS)
            if not tables:
                result.warnings.append(f"page {pageno}: no tables detected")
                continue
            for table in tables:
                rows = [[_clean_cell(c) for c in row] for row in table]
                build_drafts_from_rows(rows, f"page {pageno}", result)

    return result

"""Header detection and column mapping for BOQ spreadsheets (AR/EN)."""

from dataclasses import dataclass

from app.extract.units import normalize_text

# keyword -> field. Matching is substring-based on normalized cell text.
HEADER_KEYWORDS: dict[str, list[str]] = {
    "line_no": ["item", "no", "item no", "s.no", "sr", "sr.", "م", "بند", "رقم", "مسلسل"],
    "description": [
        "description", "desc", "item description", "work description", "particulars",
        "البيان", "بيان", "الوصف", "وصف", "تفاصيل", "الشرح",
    ],
    "quantity": [
        "qty", "qty.", "quantity", "actual qty", "qnty",
        "الكمية", "كميه", "كمية", "مقدار",
    ],
    "unit": [
        "unit", "u/m", "uom", "unit of measurement", "unit measure",
        "الوحدة", "وحدة", "وحدة القياس",
    ],
    "rate": ["rate", "unit rate", "price", "unit price", "السعر", "سعر الوحدة", "الفئة"],
    "total": ["total", "amount", "total amount", "الإجمالي", "اجمالي", "المجموع"],
}


@dataclass(frozen=True)
class HeaderMatch:
    row_index: int          # 0-based index within the scanned rows
    mapping: dict[str, int]  # field -> column index
    score: int


def _cell_matches(cell: object, field: str) -> bool:
    text = normalize_text(cell)
    if not text:
        return False
    for kw in HEADER_KEYWORDS[field]:
        kw_norm = normalize_text(kw)
        # short ambiguous tokens ("no", "م") require an exact token match
        if len(kw_norm) <= 2:
            if text == kw_norm:
                return True
        elif kw_norm in text:
            return True
    return False


def find_header(rows: list[list[object]], max_scan: int = 20) -> HeaderMatch | None:
    """Score the first `max_scan` rows; a row is a header candidate when it
    contains a description column and at least one of quantity/unit/item."""
    best: HeaderMatch | None = None
    for idx, row in enumerate(rows[:max_scan]):
        mapping: dict[str, int] = {}
        score = 0
        for col, cell in enumerate(row):
            for field in HEADER_KEYWORDS:
                if field not in mapping and _cell_matches(cell, field):
                    mapping[field] = col
                    score += 1
        has_desc = "description" in mapping
        has_signal = any(f in mapping for f in ("quantity", "unit", "line_no"))
        if has_desc and has_signal:
            candidate = HeaderMatch(row_index=idx, mapping=mapping, score=score)
            if best is None or candidate.score > best.score:
                best = candidate
    return best

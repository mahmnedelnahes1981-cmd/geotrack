"""Shared row -> BOQ draft conversion used by Excel/CSV/PDF extractors."""

from decimal import Decimal, InvalidOperation

from app.extract.base import ExtractionResult
from app.extract.base import BoqItemDraft
from app.extract.column_mapper import find_header
from app.extract.units import normalize_digits, normalize_text, normalize_unit


def parse_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = normalize_digits(normalize_text(value)).replace("٬", "").replace("٫", ".").strip()
    has_dot, has_comma = "." in text, "," in text
    if has_dot and has_comma:
        if text.rfind(",") > text.rfind("."):      # 1.234,56 (EU)
            text = text.replace(".", "").replace(",", ".")
        else:                                       # 1,234.56 (US)
            text = text.replace(",", "")
    elif has_comma:
        left, right = text.rsplit(",", 1)
        if right.isdigit() and len(right) <= 2 and left.replace(",", "").isdigit():
            text = left.replace(",", "") + "." + right   # 12,5 -> 12.5
        else:
            text = text.replace(",", "")                  # 1,234 -> 1234
    elif text.count(".") > 1:                       # 1.234.567 (EU thousands)
        text = text.replace(".", "")
    text = text.replace(" ", "")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def build_drafts_from_rows(
    rows: list[list[object]], source_label: str, result: ExtractionResult
) -> None:
    """`source_label` is used as the prefix of source_ref, e.g. "BOQ" or "page 2"."""
    match = find_header(rows)
    if match is None:
        result.warnings.append(f"{source_label}: no header row detected (need a description column + qty/unit)")
        return

    result.header_row = match.row_index if result.header_row is None else result.header_row
    result.mapping.update(match.mapping)
    header = match.mapping
    desc_col = header["description"]
    qty_col = header.get("quantity")
    unit_col = header.get("unit")
    line_no_col = header.get("line_no")

    for row_idx, row in enumerate(rows[match.row_index + 1 :], start=match.row_index + 2):
        if not any(normalize_text(c) for c in row):
            continue  # fully empty row

        def cell(col: int | None) -> object:
            return row[col] if col is not None and col < len(row) else None

        raw_desc = str(cell(desc_col) or "").strip()
        if not raw_desc:
            result.warnings.append(f"{source_label}!R{row_idx}: row skipped (empty description)")
            continue

        quantity = parse_decimal(cell(qty_col))
        unit_raw = cell(unit_col)
        unit_text = str(unit_raw).strip() if unit_raw is not None else None
        unit_info = normalize_unit(unit_text)

        confidence = Decimal("0.90")
        if quantity is None:
            confidence = Decimal("0.55")
        if unit_text and not unit_info.known:
            confidence = min(confidence, Decimal("0.70"))
        if unit_text is None:
            confidence = min(confidence, Decimal("0.65"))

        raw_row = {f"col_{i}": (None if v is None else str(v)) for i, v in enumerate(row)}
        line_no_raw = parse_decimal(cell(line_no_col)) if line_no_col is not None else None

        result.drafts.append(
            BoqItemDraft(
                line_no=int(line_no_raw) if line_no_raw is not None else None,
                raw_description=raw_desc,
                quantity=quantity,
                unit=unit_text,
                norm_unit=unit_info.base_unit if unit_info.known else None,
                unit_factor=unit_info.factor,
                confidence=confidence,
                source_ref=f"{source_label}!R{row_idx}",
                raw_row=raw_row,
            )
        )

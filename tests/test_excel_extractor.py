from decimal import Decimal

import pytest
from app.extract.excel import extract_file, parse_decimal

from conftest import FIXTURES


def test_english_xlsx_extracts_all_rows():
    result = extract_file(FIXTURES / "boq_en_micropiles.xlsx")
    assert len(result.drafts) == 6
    assert result.warnings == []
    first = result.drafts[0]
    assert first.raw_description.startswith("Drilling micropiles")
    assert first.quantity == Decimal("850")
    assert first.norm_unit == "m"
    assert first.unit_factor == Decimal("1")
    assert first.source_ref == "BOQ!R2"


def test_english_xlsx_unit_factor_ton_to_kg():
    result = extract_file(FIXTURES / "boq_en_micropiles.xlsx")
    cage = result.drafts[1]
    assert cage.unit == "ton"
    assert cage.norm_unit == "kg"
    assert cage.unit_factor == Decimal("1000")


def test_arabic_xlsx_header_detected_below_title_rows():
    result = extract_file(FIXTURES / "boq_ar_micropiles.xlsx")
    assert result.header_row == 2  # 0-based: title row, blank row, header row
    assert len(result.drafts) == 5
    qty_row = result.drafts[0]
    assert qty_row.quantity == Decimal("850")          # Arabic-Indic digits parsed
    assert qty_row.norm_unit == "m"


def test_arabic_xlsx_mixed_digit_formats():
    result = extract_file(FIXTURES / "boq_ar_micropiles.xlsx")
    cage = result.drafts[1]
    assert cage.quantity == Decimal("12.5")
    assert cage.norm_unit == "kg"
    note = result.drafts[4]
    assert note.norm_unit is None or note.unit == "مقطوعية"
    assert result.drafts[4].unit == "مقطوعية"


def test_english_csv_comma_delimited():
    result = extract_file(FIXTURES / "boq_en.csv")
    assert len(result.drafts) == 4
    assert result.drafts[0].quantity == Decimal("850")


def test_arabic_csv_windows1256_roundtrip():
    result = extract_file(FIXTURES / "boq_ar_windows1256.csv")
    assert len(result.drafts) == 3
    assert "حفر" in result.drafts[0].raw_description


def test_unknown_units_lower_confidence():
    result = extract_file(FIXTURES / "boq_unknown_units.xlsx")
    by_line = {d.line_no: d for d in result.drafts}
    assert by_line[1].confidence == Decimal("0.70")   # unit not recognized
    assert by_line[2].confidence == Decimal("0.55")   # quantity missing
    assert by_line[1].norm_unit is None


def test_unsupported_extension():
    with pytest.raises(ValueError):
        extract_file("whatever.docx")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1,234.56", Decimal("1234.56")),
        ("1.234,56", Decimal("1234.56")),
        ("12,5", Decimal("12.5")),
        ("1,234", Decimal("1234")),
        ("1.234.567", Decimal("1234567")),
        ("٨٥٠", Decimal("850")),
        ("١٢٫٥", Decimal("12.5")),
        (None, None),
        ("", None),
    ],
)
def test_parse_decimal_formats(raw, expected):
    assert parse_decimal(raw) == expected

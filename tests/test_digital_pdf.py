from decimal import Decimal

from app.extract.arabic import fix_visual_order_arabic
from app.extract.pdf import extract_pdf

from conftest import FIXTURES


def test_en_pdf_extracts_rows():
    result = extract_pdf(FIXTURES / "boq_en_micropiles.pdf")
    assert result.warnings == []
    assert len(result.drafts) == 6
    first = result.drafts[0]
    assert first.raw_description.startswith("Drilling micropiles")
    assert first.quantity == Decimal("850")
    assert first.norm_unit == "m"
    assert first.source_ref.startswith("page 1!R")


def test_ar_pdf_arabic_comes_out_logical_not_mirrored():
    result = extract_pdf(FIXTURES / "boq_ar_micropiles.pdf")
    assert result.warnings == []
    assert len(result.drafts) == 5
    for draft in result.drafts:
        # presentation-form codepoints must be fully repaired
        assert not any(0xFB50 <= ord(ch) <= 0xFDFF or 0xFE70 <= ord(ch) <= 0xFEFF
                       for ch in draft.raw_description)
    assert "خوازيق" in result.drafts[0].raw_description


def test_ar_pdf_quantities_and_units():
    result = extract_pdf(FIXTURES / "boq_ar_micropiles.pdf")
    assert result.drafts[0].quantity == Decimal("850")
    assert result.drafts[0].norm_unit == "m"
    cage = result.drafts[1]
    assert cage.quantity == Decimal("12.5")
    assert cage.norm_unit == "kg"          # طن -> كجم, factor 1000
    assert cage.unit_factor == Decimal("1000")
    concrete = result.drafts[2]
    assert concrete.norm_unit == "m3"


def test_ar_pdf_line_numbers_and_header():
    result = extract_pdf(FIXTURES / "boq_ar_micropiles.pdf")
    assert result.header_row == 0
    line_nos = [d.line_no for d in result.drafts]
    assert line_nos == [1, 2, 3, 4, 5]


def test_scanned_pdf_without_text_layer_warns():
    result = extract_pdf(FIXTURES / "boq_blank_scanned.pdf")
    assert result.drafts == []
    assert any("text layer" in w for w in result.warnings)


def test_fix_visual_order_arabic_passthrough_logical_text():
    logical = "حفر خوازيق دقيقة"
    assert fix_visual_order_arabic(logical) == logical
    assert fix_visual_order_arabic("850 m") == "850 m"


def test_fix_visual_order_arabic_roundtrip_from_generator():
    import arabic_reshaper
    from bidi.algorithm import get_display

    logical = "حفر خوازيق دقيقة بقفص حديدي"
    visual = get_display(arabic_reshaper.ArabicReshaper().reshape(logical))
    assert fix_visual_order_arabic(visual) == logical

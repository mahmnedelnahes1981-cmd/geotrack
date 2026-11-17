"""Generate synthetic golden BOQ fixtures (AR + EN) for tests.

Re-run any time: python scripts/make_golden_files.py
"""

import unicodedata
from pathlib import Path

from openpyxl import Workbook

WINDOWS_FONTS = Path("C:/Windows/Fonts")

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
FIXTURES.mkdir(parents=True, exist_ok=True)


def make_en_xlsx() -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "BOQ"
    ws.append(["Item", "Description", "Qty", "Unit"])
    rows = [
        (1, "Drilling micropiles Ø200mm to depth 12m in mixed soil", 850, "m"),
        (2, "Reinforcement cage Ø150mm for micropiles", 12.5, "ton"),
        (3, "Micropile concrete C30/37", 96, "m3"),
        (4, "Sheet pile type AZ 18, driven and extracted", 420, "m2"),
        (5, "Jet grouting soil improvement, columns Ø600mm", 1500, "m3"),
        (6, "Mobilisation and demobilisation", 1, "L.S."),
    ]
    for row in rows:
        ws.append(list(row))
    path = FIXTURES / "boq_en_micropiles.xlsx"
    wb.save(path)
    return path


def make_ar_xlsx() -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Table"
    ws.append(["مقايسة أعمال خوازيق دقيقة — مشروع الستائر اللوحية"])
    ws.append([None, None, None, None])
    ws.append(["م", "البيان", "الكمية", "الوحدة"])
    rows = [
        (1, "حفر خوازيق دقيقة قطر ٢٠٠ مم حتى عمق ١٢ م في تربة مختلطة", "٨٥٠", "م"),
        (2, "تسليح الخوازيق الدقيقة بقفص حديدي قطر ١٥٠ مم", 12.5, "طن"),
        (3, "صب خرسانة الخوازيق الدقيقة درجة C30/37", 96, "م3"),
        (4, "توريد وتركيب ستائر لوحية نوع AZ 18", 420, "م٢"),
        (5, "تحريك المعدات والمنشآت المؤقتة", 1, "مقطوعية"),
    ]
    for row in rows:
        ws.append(list(row))
    path = FIXTURES / "boq_ar_micropiles.xlsx"
    wb.save(path)
    return path


def make_en_csv() -> Path:
    path = FIXTURES / "boq_en.csv"
    path.write_text(
        "Item,Description,Qty,Unit\n"
        "1,Drilling micropiles 200mm dia to 12m depth,850,m\n"
        "2,Reinforcement cage 150mm dia,12.5,ton\n"
        "3,Micropile concrete C30/37,96,m3\n"
        "4,Sheet piles AZ 18 driven,420,m2\n",
        encoding="utf-8",
    )
    return path


def make_ar_csv_windows1256() -> Path:
    path = FIXTURES / "boq_ar_windows1256.csv"
    text = (
        "م;البيان;الكمية;الوحدة\n"
        "1;حفر خوازيق دقيقة قطر 200 مم حتى عمق 12 متر;850;م\n"
        "2;تسليح الخوازيق الدقيقة بقفص حديدي قطر 150 مم;12.5;طن\n"
        "3;صب خرسانة الخوازيق الدقيقة درجة C30/37;96;م3\n"
    )
    path.write_bytes(text.encode("windows-1256"))
    return path


def _has_arabic(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06ff" for ch in text)


def _shape(text: str) -> str:
    """Visual-order rendering of Arabic for PDF output (font shaping is manual)."""
    import arabic_reshaper
    from bidi.algorithm import get_display

    if not _has_arabic(text):
        return text
    return get_display(arabic_reshaper.ArabicReshaper().reshape(text))


def _render_table(pdf, col_widths, rows, font_family, font_style, font_size, rtl=False, row_height=8):
    page_right = pdf.w - pdf.r_margin

    def cell_x(index: int) -> float:
        if not rtl:
            return pdf.l_margin + sum(col_widths[:index])
        return page_right - sum(col_widths[: index + 1])

    for row in rows:
        y = pdf.get_y()
        for i, (width, value) in enumerate(zip(col_widths, row)):
            text = _shape(str(value))
            pdf.set_xy(cell_x(i), y)
            pdf.cell(width, row_height, text, border=1, align="C")
        pdf.set_y(y + row_height)


def make_en_pdf() -> Path:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()
    pdf.set_margins(15, 15, 15)
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("helvetica", "B", 13)
    pdf.cell(0, 9, "BOQ - Micropiles & Sheet Piles (Project GT-001)", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    rows = [
        ("Item", "Description", "Qty", "Unit"),
        ("1", "Drilling micropiles 200mm dia to depth 12m in mixed soil", "850", "m"),
        ("2", "Reinforcement cage 150mm dia for micropiles", "12.5", "ton"),
        ("3", "Micropile concrete C30/37", "96", "m3"),
        ("4", "Sheet pile type AZ 18, driven and extracted", "420", "m2"),
        ("5", "Jet grouting soil improvement, columns 600mm dia", "1500", "m3"),
        ("6", "Mobilisation and demobilisation", "1", "L.S."),
    ]
    widths = [16, 118, 22, 24]
    pdf.set_font("helvetica", "", 9)
    _render_table(pdf, widths, rows, "helvetica", "", 9)
    path = FIXTURES / "boq_en_micropiles.pdf"
    pdf.output(str(path))
    return path


def make_ar_pdf() -> Path:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()
    pdf.set_margins(15, 15, 15)
    pdf.add_font("Tahoma", "", str(WINDOWS_FONTS / "tahoma.ttf"))
    pdf.set_text_color(30, 30, 30)

    pdf.set_font("Tahoma", "", 13)
    pdf.cell(0, 9, _shape("مقايسة أعمال خوازيق دقيقة — مشروع الستائر اللوحية"),
             new_x="LMARGIN", new_y="NEXT", align="R")
    pdf.ln(2)

    rows = [
        ("م", "البيان", "الكمية", "الوحدة"),
        ("1", "حفر خوازيق دقيقة قطر ٢٠٠ مم حتى عمق ١٢ م في تربة مختلطة", "850", "م"),
        ("2", "تسليح الخوازيق الدقيقة بقفص حديدي قطر ١٥٠ مم", "12.5", "طن"),
        ("3", "صب خرسانة الخوازيق الدقيقة درجة C30/37", "96", "م3"),
        ("4", "توريد وتركيب ستائر لوحية نوع AZ 18", "420", "م٢"),
        ("5", "تحريك المعدات والمنشآت المؤقتة", "1", "مقطوعية"),
    ]
    widths = [12, 110, 26, 32]
    pdf.set_font("Tahoma", "", 9)
    _render_table(pdf, widths, rows, "Tahoma", "", 9, rtl=True)
    path = FIXTURES / "boq_ar_micropiles.pdf"
    pdf.output(str(path))
    return path


def make_blank_scanned_pdf() -> Path:
    """Simulates a scanned PDF: no text layer at all (only vector artwork)."""
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.add_page()
    pdf.rect(30, 40, 150, 200, style="D")
    pdf.line(40, 60, 160, 60)
    path = FIXTURES / "boq_blank_scanned.pdf"
    pdf.output(str(path))
    return path


def make_unknown_units_xlsx() -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Odd"
    ws.append(["Item", "Description", "Qty", "Unit"])
    ws.append([1, "Load test micropile to 1.5x design load", 2, "test"])
    ws.append([2, "As-built drawings and documentation", None, "doc"])
    path = FIXTURES / "boq_unknown_units.xlsx"
    wb.save(path)
    return path


if __name__ == "__main__":
    for make in (make_en_xlsx, make_ar_xlsx, make_en_csv, make_ar_csv_windows1256,
                 make_unknown_units_xlsx, make_en_pdf, make_ar_pdf, make_blank_scanned_pdf):
        print("wrote", make())

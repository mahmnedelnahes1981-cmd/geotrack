"""Shared helpers for GeoTrack PDF builders (Arabic + Latin, RTL)."""

from pathlib import Path

_FONT_DIR = Path("C:/Windows/Fonts")
_REGULAR = _FONT_DIR / "tahoma.ttf"
_BOLD = _FONT_DIR / "tahomabd.ttf"

INK = (36, 26, 2)
SLATE = (31, 42, 53)
AMBER = (240, 180, 41)
MUTED = (120, 132, 145)
ROW_ALT = (250, 246, 238)


def has_arabic(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06ff" for ch in text)


def shape(text: str) -> str:
    if not has_arabic(text):
        return text
    import arabic_reshaper
    from bidi.algorithm import get_display

    return get_display(arabic_reshaper.ArabicReshaper().reshape(text))


def fmt_qty(value) -> str:
    text = f"{value:,.3f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def fmt_money(value) -> str:
    return f"{value:,.2f}"


def add_fonts(doc) -> None:
    doc.add_font("Tahoma", "", str(_REGULAR))
    doc.add_font("Tahoma", "B", str(_BOLD))


def make_doc():
    from fpdf import FPDF

    class GeoDoc(FPDF):
        def footer(self) -> None:  # noqa: N802 - fpdf2 hook
            self.set_y(-11)
            self.set_font("Tahoma", "", 7)
            self.set_text_color(*MUTED)
            self.cell(0, 6, f"{getattr(self, 'footer_text', 'GeoTrack')}{self.page_no()}/{{nb}}", align="C")

    doc = GeoDoc(format="A4", unit="mm")
    doc.set_auto_page_break(auto=True, margin=16)
    doc.set_margins(10, 10, 10)
    add_fonts(doc)
    doc.alias_nb_pages()
    doc.add_page()
    return doc


def text(doc, x, y, w, t, size, style="", color=INK, align="R"):
    doc.set_xy(x, y)
    doc.set_font("Tahoma", style, size)
    doc.set_text_color(*color)
    doc.cell(w, size * 0.55, shape(t), align=align)


def draw_header_band(doc, settings, left_en: str, left_ar: str) -> None:
    right = doc.w - doc.r_margin
    y = 12
    # company block (right)
    text(doc, right - 100, y, 100, settings.company_name_ar, 13, "B", INK, "R")
    text(doc, right - 100, y + 6, 100, settings.company_name_en, 8, "", MUTED, "R")
    text(doc, right - 100, y + 11, 100, settings.company_address_ar, 7, "", MUTED, "R")
    contacts = " · ".join(x for x in (settings.company_phone, settings.company_email,
                                      settings.company_tax_id and f"الرقم الضريبي: {settings.company_tax_id}") if x)
    if contacts:
        text(doc, right - 100, y + 15.5, 100, contacts, 7, "", MUTED, "R")
    # document type block (left)
    text(doc, doc.l_margin, y - 1, 85, left_en, 20, "B", SLATE, "L")
    text(doc, doc.l_margin, y + 8, 85, left_ar, 14, "B", AMBER, "L")
    doc.set_fill_color(*AMBER)
    doc.rect(doc.l_margin, y + 20, right - doc.l_margin, 1.6, style="F")


def wrap_text(doc, text_value: str, font_size: float, max_width: float) -> list[str]:
    words = text_value.split(" ")
    lines, current = [], ""
    doc.set_font("Tahoma", "", font_size)
    for word in words:
        candidate = (current + " " + word).strip()
        if doc.get_string_width(candidate) <= max_width * 0.92 or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines

"""Quote PDF generator (fpdf2 + manual Arabic shaping — the stack that works offline here)."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.config import get_settings
from app.pricing import quote_code

_FONT_DIR = Path("C:/Windows/Fonts")
_REGULAR = _FONT_DIR / "tahoma.ttf"
_BOLD = _FONT_DIR / "tahomabd.ttf"

INK = (36, 26, 2)          # near-black warm
SLATE = (31, 42, 53)       # dark slate panel
AMBER = (240, 180, 41)     # GeoTrack accent
MUTED = (120, 132, 145)
PAPER = (255, 255, 255)
ROW_ALT = (250, 246, 238)


def _has_arabic(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06ff" for ch in text)


def _shape(text: str) -> str:
    if not _has_arabic(text):
        return text
    import arabic_reshaper
    from bidi.algorithm import get_display

    return get_display(arabic_reshaper.ArabicReshaper().reshape(text))


def _fmt_qty(value: Decimal) -> str:
    text = f"{value:,.3f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _fmt_money(value: Decimal) -> str:
    return f"{value:,.2f}"


class QuotePDF:
    def __init__(self) -> None:
        from fpdf import FPDF

        class _Doc(FPDF):
            def footer(self) -> None:  # noqa: N802 - fpdf2 hook
                settings = get_settings()
                self.set_y(-11)
                self.set_font("Tahoma", "", 7)
                self.set_text_color(*MUTED)
                self.cell(0, 6, _shape(f"{settings.company_name_en}  ·  عرض سعر {self._quote_code}  ·  صفحة {self.page_no()}/{{nb}}"),
                          align="C")

        self.doc = _Doc(format="A4", unit="mm")
        self.doc._quote_code = ""   # filled by build()
        self.doc.alias_nb_pages()
        self.doc.set_auto_page_break(auto=True, margin=16)
        self.doc.set_margins(10, 10, 10)
        self.doc.add_page()
        self.doc.add_font("Tahoma", "", str(_REGULAR))
        self.doc.add_font("Tahoma", "B", str(_BOLD))

    # -- low-level helpers ---------------------------------------------------
    def _text(self, x: float, y: float, w: float, text: str, size: float,
              style: str = "", color=INK, align: str = "R") -> None:
        self.doc.set_xy(x, y)
        self.doc.set_font("Tahoma", style, size)
        self.doc.set_text_color(*color)
        self.doc.cell(w, size * 0.55, _shape(text), align=align)

    def _right_edge(self) -> float:
        return self.doc.w - self.doc.r_margin

    def _wrap(self, text: str, font_size: float, max_width: float) -> list[str]:
        words = text.split(" ")
        lines, current = [], ""
        self.doc.set_font("Tahoma", "", font_size)
        for word in words:
            candidate = (current + " " + word).strip()
            if self.doc.get_string_width(candidate) <= max_width * 0.92 or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    # -- sections -------------------------------------------------------------
    def _header_band(self, settings) -> None:
        doc = self.doc
        right = self._right_edge()
        y = 12
        # company block (right)
        self._text(right - 100, y, 100, settings.company_name_ar, 13, "B", INK, "R")
        self._text(right - 100, y + 6, 100, settings.company_name_en, 8, "", MUTED, "R")
        self._text(right - 100, y + 11, 100, settings.company_address_ar, 7, "", MUTED, "R")
        contacts = " · ".join(x for x in (settings.company_phone, settings.company_email,
                                          settings.company_tax_id and f"الرقم الضريبي: {settings.company_tax_id}") if x)
        if contacts:
            self._text(right - 100, y + 15.5, 100, contacts, 7, "", MUTED, "R")
        # document type block (left)
        self._text(doc.l_margin, y - 1, 80, "QUOTATION", 22, "B", SLATE, "L")
        self._text(doc.l_margin, y + 7.5, 80, "عرض سعر", 15, "B", AMBER, "L")
        # amber rule
        doc.set_fill_color(*AMBER)
        doc.rect(doc.l_margin, y + 20, right - doc.l_margin, 1.6, style="F")

    def _meta_rows(self, quote, project, client, quote_c: str) -> None:
        settings = get_settings()
        doc = self.doc
        right = self._right_edge()
        y = 38
        rows = [
            ("رقم العرض", quote_c),
            ("التاريخ", datetime.now().strftime("%Y-%m-%d")),
            ("العميل", client.name if client else "—"),
            ("المشروع", project.name if project else "—"),
            ("العملة", quote.currency),
            ("صلاحية العرض", f"{settings.quote_validity_days} يومًا من تاريخ الإصدار"),
        ]
        for label, value in rows:
            self._text(right - 28, y, 28, label + ":", 8.5, "B", MUTED, "R")
            self._text(doc.l_margin, y, right - doc.l_margin - 30, value, 8.5, "", INK, "R")
            y += 5.6

    def _lines_table(self, lines) -> None:
        doc = self.doc
        right = self._right_edge()
        widths = [11, 73, 19, 16, 33, 38]   # م | البيان | الكمية | الوحدة | سعر الوحدة | الإجمالي
        headers = ["م", "البيان", "الكمية", "الوحدة", "سعر الوحدة", "الإجمالي"]

        y = 76
        # header row
        doc.set_fill_color(*SLATE)
        doc.rect(doc.l_margin, y, right - doc.l_margin, 9, style="F")
        x = right
        for width, header in zip(widths, headers):
            x -= width
            self._text(x, y + 2.2, width, header, 8.5, "B", AMBER, "C")
        y += 9

        for index, row in enumerate(lines, start=1):
            lines_wrapped = self._wrap(row["description"], 8, widths[1] - 4)
            row_height = max(7.5, len(lines_wrapped) * 5.3 + 2.5)
            if y + row_height > doc.h - 40:  # keep room for totals/terms
                doc.add_page()
                y = 14
            fill = index % 2 == 0
            if fill:
                doc.set_fill_color(*ROW_ALT)
                doc.rect(doc.l_margin, y, right - doc.l_margin, row_height, style="F")
            x = right
            cells = [
                str(index),
                None,  # description, drawn with wrap below
                _fmt_qty(row["qty"]),
                row["unit"],
                _fmt_money(row["unit_price"]),
                _fmt_money(row["line_total"]),
            ]
            # numeric/simple cells
            for width, value in zip(widths, cells):
                x -= width
                if value is None:
                    continue
                align = "C" if width <= 19 else "L"
                self._text(x, y + (row_height - 5) / 2, width, value, 8, "", INK, align)
            # description cell (right aligned, wrapped)
            desc_x = right - widths[0] - widths[1]
            text_y = y + 1.8
            for wrapped in lines_wrapped:
                self._text(desc_x + 1, text_y, widths[1] - 2, wrapped, 8, "", INK, "R")
                text_y += 5.3
            # row separators
            doc.set_draw_color(225, 220, 208)
            doc.set_line_width(0.2)
            doc.line(doc.l_margin, y + row_height, right, y + row_height)
            y += row_height
        return y

    def _totals_block(self, quote) -> float:
        doc = self.doc
        right = self._right_edge()
        subtotal = Decimal(quote.totals_json["subtotal"])
        tax = Decimal(quote.totals_json["tax"])
        grand = Decimal(quote.totals_json["grand_total"])

        y = doc.get_y() + 4
        if y > doc.h - 55:
            doc.add_page()
            y = 14
        box_w = 78
        x = right - box_w
        rows = [
            ("الإجمالي قبل الضريبة", _fmt_money(subtotal)),
            (f"الضريبة ({quote.tax_rate}%)", _fmt_money(tax)),
        ]
        for label, value in rows:
            self._text(x, y, box_w - 26, label, 9, "", MUTED, "R")
            self._text(x, y, box_w, value, 9, "", INK, "L")
            y += 6.2
        # grand total band: value flush-left, label flush-right (no overlap)
        doc.set_fill_color(*AMBER)
        doc.rect(x, y, box_w, 10, style="F")
        self._text(x + 2, y + 2.4, 30, f"{_fmt_money(grand)} {quote.currency}", 9.5, "B", INK, "L")
        self._text(x, y + 2.4, box_w - 2, "الإجمالي شامل الضريبة", 9.5, "B", INK, "R")
        return y + 14

    def _terms(self, y: float) -> None:
        doc = self.doc
        settings = get_settings()
        right = self._right_edge()
        if y > doc.h - 45:
            doc.add_page()
            y = 14
        self._text(right - 80, y, 80, "الشروط والأحكام", 9.5, "B", SLATE, "R")
        doc.set_draw_color(*AMBER)
        doc.set_line_width(0.8)
        doc.line(right - 28, y + 6.5, right, y + 6.5)
        terms = [
            "شروط الدفع: 30% دفعة عند التوقيع على العقد، 40% عند منتصف التنفيذ، 30% عند الاستلام النهائي وقبول الأعمال.",
            f"مدة صلاحية هذا العرض: {settings.quote_validity_days} يومًا من تاريخ الإصدار.",
            "التنفيذ يتم حسب رسومات العقد ومواصفات المشروع المعتمدة وأصول المهنة.",
            "أي أعمال إضافية أو تعديلات تُسعّر بأمر تغيير (Variation Order) معتمد من العميل قبل التنفيذ.",
            "هذا العرض غير ملزم إلا بعد توقيع العقد والموافقة النهائية من الطرفين.",
        ]
        ty = y + 10
        for term in terms:
            for line in self._wrap(term, 7.5, right - doc.l_margin - 6):
                self._text(doc.l_margin + 4, ty, right - doc.l_margin - 4, line, 7.5, "", INK, "R")
                ty += 5
            ty += 0.8
        # signature blocks
        ty += 6
        if ty > doc.h - 30:
            doc.add_page()
            ty = 14
        half = (right - doc.l_margin) / 2 - 8
        self._text(right - half, ty, half, "بتفويض من الشركة", 8, "B", MUTED, "R")
        self._text(doc.l_margin, ty, half, "موافقة العميل", 8, "B", MUTED, "R")
        doc.set_draw_color(*MUTED)
        doc.set_line_width(0.3)
        doc.line(right - half, ty + 16, right, ty + 16)
        doc.line(doc.l_margin, ty + 16, doc.l_margin + half, ty + 16)

    # -- public API -----------------------------------------------------------
    def build(self, quote, project, client, lines) -> bytes:
        code = quote_code(quote)
        self.doc._quote_code = code
        settings = get_settings()
        self._header_band(settings)
        self._meta_rows(quote, project, client, code)
        table_end_y = self._lines_table(lines)
        self.doc.set_y(max(table_end_y, 76))
        totals_end_y = self._totals_block(quote)
        self._terms(totals_end_y + 2)
        return bytes(self.doc.output())


def build_quote_pdf(quote, project, client, lines) -> bytes:
    return QuotePDF().build(quote, project, client, lines)

"""As-built final invoice PDF (same look & feel as the quote PDF)."""

from decimal import Decimal

from app.config import get_settings
from app.pdf_common import (AMBER, INK, MUTED, ROW_ALT, SLATE,
                            draw_header_band, fmt_money, fmt_qty,
                            make_doc, shape, text, wrap_text)


def build_invoice_pdf(invoice, project, client, lines, totals: dict) -> bytes:
    settings = get_settings()
    doc = make_doc()
    doc.footer_text = f"{settings.company_name_en}  ·  {invoice.invoice_number}  ·  page "
    right = doc.w - doc.r_margin

    draw_header_band(doc, settings, "FINAL INVOICE", "فاتورة ختامية")

    # meta rows
    y = 38
    meta = [
        ("رقم الفاتورة", invoice.invoice_number),
        ("التاريخ", invoice.created_at.strftime("%Y-%m-%d")),
        ("مرجع العقد", totals.get("quote_code", "—")),
        ("العميل", client.name if client else "—"),
        ("المشروع", project.name if project else "—"),
        ("العملة", invoice.currency),
    ]
    for label, value in meta:
        text(doc, right - 28, y, 28, label + ":", 8.5, "B", MUTED, "R")
        text(doc, doc.l_margin, y, right - doc.l_margin - 30, value, 8.5, "", INK, "R")
        y += 5.6

    # contract vs executed strip
    y += 3
    strip_h = 16
    box_w = (right - doc.l_margin - 6) / 2
    contract_txt = fmt_money(Decimal(str(invoice.contract_value)))
    executed_txt = fmt_money(Decimal(str(invoice.executed_subtotal)))
    doc.set_fill_color(*SLATE)
    doc.rect(doc.l_margin, y, box_w, strip_h, style="F")
    doc.set_fill_color(*AMBER)
    doc.rect(doc.l_margin + box_w + 6, y, box_w, strip_h, style="F")
    text(doc, doc.l_margin + 2, y + 2.5, box_w - 4, f"{contract_txt} {invoice.currency}", 12, "B", MUTED, "C")
    text(doc, doc.l_margin + 2, y + 9, box_w - 4, "قيمة العقد (المقايسة)", 8, "", MUTED, "C")
    text(doc, doc.l_margin + box_w + 8, y + 2.5, box_w - 4, f"{executed_txt} {invoice.currency}", 12, "B", INK, "C")
    text(doc, doc.l_margin + box_w + 8, y + 9, box_w - 4, "المنفذ فعليًا من السجل الميداني", 8, "B", INK, "C")

    # table header
    y = 74
    widths = [11, 64, 22, 22, 14, 24, 31]   # م | البيان | المتعاقد | المنفذ | الوحدة | سعر الوحدة | قيمة المنفذ
    headers = ["م", "البيان", "المتعاقد", "المنفذ", "الوحدة", "سعر الوحدة", "قيمة المنفذ"]
    doc.set_fill_color(*SLATE)
    doc.rect(doc.l_margin, y, right - doc.l_margin, 9, style="F")
    x = right
    for width, header in zip(widths, headers):
        x -= width
        text(doc, x, y + 2.2, width, header, 8, "B", AMBER, "C")
    y += 9

    for index, row in enumerate(lines, start=1):
        wrapped = wrap_text(doc, row["description"], 8, widths[1] - 4)
        row_height = max(7.5, len(wrapped) * 5.3 + 2.5)
        if y + row_height > doc.h - 40:
            doc.add_page()
            y = 14
        if index % 2 == 0:
            doc.set_fill_color(*ROW_ALT)
            doc.rect(doc.l_margin, y, right - doc.l_margin, row_height, style="F")
        x = right
        cells = [str(index), None, fmt_qty(Decimal(str(row["contract_qty"]))),
                 fmt_qty(Decimal(str(row["executed_qty"]))), row["unit"],
                 fmt_money(Decimal(str(row["unit_price"]))), fmt_money(Decimal(str(row["executed_value"])))]
        for width, value in zip(widths, cells):
            x -= width
            if value is None:
                continue
            align = "C" if width <= 24 else "L"
            text(doc, x, y + (row_height - 5) / 2, width, value, 8, "", INK, align)
        desc_x = right - widths[0] - widths[1]
        ty = y + 1.8
        for line in wrapped:
            text(doc, desc_x + 1, ty, widths[1] - 2, line, 8, "", INK, "R")
            ty += 5.3
        doc.set_draw_color(225, 220, 208)
        doc.set_line_width(0.2)
        doc.line(doc.l_margin, y + row_height, right, y + row_height)
        y += row_height

    doc.set_y(max(y, 76) + 2)

    # exclusions
    exclusions = totals.get("exclusions", [])
    if exclusions:
        if doc.get_y() > doc.h - 45:
            doc.add_page()
            doc.set_y(14)
        text(doc, right - 70, doc.get_y(), 70, "بنود مستبعدة من الفاتورة (تحتاج اعتماد يدوي):", 8, "B", MUTED, "R")
        ey = doc.get_y() + 6
        for excl in exclusions:
            line = f"{excl['code']} — {Decimal(str(excl.get('contract_value', '0'))):,.2f} {invoice.currency} · {excl.get('reason', '')}"
            text(doc, doc.l_margin + 4, ey, right - doc.l_margin - 4, line, 7, "", MUTED, "R")
            ey += 5
        doc.set_y(ey + 2)

    # totals block
    y = doc.get_y() + 2
    if y > doc.h - 40:
        doc.add_page()
        y = 14
    box_w = 78
    x = right - box_w
    subtotal = Decimal(str(invoice.executed_subtotal))
    tax = Decimal(str(invoice.executed_tax))
    grand = Decimal(str(invoice.executed_total))
    for label, value in (("صافي الأعمال المنفذة", fmt_money(subtotal)),
                         (f"الضريبة ({invoice.tax_rate}%)", fmt_money(tax))):
        text(doc, x, y, box_w - 26, label, 9, "", MUTED, "R")
        text(doc, x, y, box_w, value, 9, "", INK, "L")
        y += 6.2
    doc.set_fill_color(*AMBER)
    doc.rect(x, y, box_w, 10, style="F")
    text(doc, x + 2, y + 2.4, 30, f"{fmt_money(grand)} {invoice.currency}", 9.5, "B", INK, "L")
    text(doc, x, y + 2.4, box_w - 2, "الإجمالي مستحق الدفع", 9.5, "B", INK, "R")
    y += 16

    # basis note + signatures
    if y > doc.h - 35:
        doc.add_page()
        y = 14
    text(doc, right - 120, y, 120, "الأساس: كميات السجل اليومي للموقع × أسعار العرض المعتمد. البنود النفعية تُعامل بالمراحل الفعلية.", 7, "", MUTED, "R")
    ty = y + 10
    half = (right - doc.l_margin) / 2 - 8
    text(doc, right - half, ty, half, "عن الشركة", 8, "B", MUTED, "R")
    text(doc, doc.l_margin, ty, half, "استلام العميل", 8, "B", MUTED, "R")
    doc.set_draw_color(*MUTED)
    doc.set_line_width(0.3)
    doc.line(right - half, ty + 14, right, ty + 14)
    doc.line(doc.l_margin, ty + 14, doc.l_margin + half, ty + 14)

    return bytes(doc.output())

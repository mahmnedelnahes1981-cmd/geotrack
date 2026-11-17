"""As-built drilling report: formal PDF listing every field log + summary.
Meant for the consultant/client handover at project closure.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import DailyLog, Rig
from app.pdf_common import (AMBER, INK, MUTED, ROW_ALT, SLATE,
                            draw_header_band, fmt_qty, make_doc, text, wrap_text)


def build_report_pdf(session: Session, project, client, rig, quote_code: str | None) -> bytes:
    settings = get_settings()
    doc = make_doc()
    doc.footer_text = f"{settings.company_name_en}  ·  As-Built Report — {project.name[:40]}  ·  page "
    right = doc.w - doc.r_margin

    logs = session.scalars(
        select(DailyLog).where(DailyLog.project_id == project.id)
        .order_by(DailyLog.log_date, DailyLog.id)
    ).all()

    draw_header_band(doc, settings, "AS-BUILT REPORT", "تقرير فني للتنفيذ")

    y = 38
    meta = [
        ("المشروع", project.name),
        ("العميل", client.name if client else "—"),
        ("مرجع العقد", quote_code or "—"),
        ("الحفار", f"{rig.code} — {rig.name}" if rig else "—"),
        ("الفترة", f"{logs[0].log_date.isoformat()} → {logs[-1].log_date.isoformat()}" if logs else "لا توجد سجلات"),
        ("تاريخ الإصدار", date.today().isoformat()),
    ]
    for label, value in meta:
        text(doc, right - 28, y, 28, label + ":", 8.5, "B", MUTED, "R")
        text(doc, doc.l_margin, y, right - doc.l_margin - 30, value, 8.5, "", INK, "R")
        y += 5.6

    y += 3
    text(doc, right - 150, y, 150, "بيان الأعمال المنفذة فعليًا حسب سجل الموقع اليومي", 9, "B", SLATE, "R")
    y += 7

    # table: م | التاريخ | الخازوق | الحفار | عمق (م) | خرسانة (م³) | ستائر (م²) | ساعات | ملاحظات التربة
    widths = [9, 21, 16, 18, 17, 19, 18, 16, 56]
    headers = ["م", "التاريخ", "الخازوق", "الحفار", "عمق (م)", "خرسانة (م³)", "ستائر (م²)", "ساعات", "ملاحظات التربة"]
    doc.set_fill_color(*SLATE)
    doc.rect(doc.l_margin, y, right - doc.l_margin, 9, style="F")
    x = right
    for width, header in zip(widths, headers):
        x -= width
        text(doc, x, y + 2.2, width, header, 7.5, "B", AMBER, "C")
    y += 9

    rigs_map = {r.id: r.code for r in session.scalars(select(Rig))}
    for index, log in enumerate(logs, start=1):
        note = log.soil_notes or log.breakdown_notes or log.remarks or ""
        note_lines = wrap_text(doc, note, 6.5, widths[8] - 3)[:2] if note else ["—"]
        row_height = max(7.0, len(note_lines) * 4.6 + 2.5)
        if y + row_height > doc.h - 45:
            doc.add_page()
            y = 14
        if index % 2 == 0:
            doc.set_fill_color(*ROW_ALT)
            doc.rect(doc.l_margin, y, right - doc.l_margin, row_height, style="F")
        x = right
        cells = [
            str(index),
            log.log_date.strftime("%Y-%m-%d"),
            log.pile_id or "—",
            rigs_map.get(log.rig_id, "—") if log.rig_id else "—",
            fmt_qty(log.depth_m),
            fmt_qty(log.concrete_m3),
            fmt_qty(log.sheet_pile_m2),
            fmt_qty(log.operating_hours),
            None,
        ]
        for width, value in zip(widths, cells):
            x -= width
            if value is None:
                continue
            align = "C"
            text(doc, x, y + (row_height - 4.5) / 2, width, value, 6.8, "", INK, align)
        note_x = right - sum(widths[:9])
        ty = y + 1.6
        for line in note_lines:
            text(doc, note_x + 1.5, ty, widths[8] - 3, line, 6.5, "", INK, "R")
            ty += 4.6
        doc.set_draw_color(225, 220, 208)
        doc.set_line_width(0.2)
        doc.line(doc.l_margin, y + row_height, right, y + row_height)
        y += row_height

    # summary block
    y += 6
    if y > doc.h - 60:
        doc.add_page()
        y = 14
    text(doc, right - 60, y, 60, "ملخص الإجماليات", 9.5, "B", SLATE, "R")
    doc.set_draw_color(*AMBER)
    doc.set_line_width(0.8)
    doc.line(right - 22, y + 6, right, y + 6)

    total_depth = sum((l.depth_m for l in logs), Decimal("0"))
    total_concrete = sum((l.concrete_m3 for l in logs), Decimal("0"))
    total_sheet = sum((l.sheet_pile_m2 for l in logs), Decimal("0"))
    total_hours = sum((l.operating_hours for l in logs), Decimal("0"))
    pile_count = len([l for l in logs if l.pile_id])
    max_depth = max((l.depth_m for l in logs), default=Decimal("0"))
    avg_depth = (total_depth / Decimal(pile_count)) if pile_count else Decimal("0")
    issue_days = len([l for l in logs if (l.soil_notes or l.breakdown_notes)])

    summary_rows = [
        ("عدد السجلات / أيام العمل", str(len(logs))),
        ("عدد الخوازيق المُنفذة", str(pile_count)),
        ("إجمالي الأطوال المنفذة", f"{fmt_qty(total_depth)} م"),
        ("أكبر عمق خازوق", f"{fmt_qty(max_depth)} م"),
        ("متوسط عمق الخازوق", f"{fmt_qty(avg_depth)} م"),
        ("إجمالي الخرسانة المصبوبة", f"{fmt_qty(total_concrete)} م³"),
        ("إجمالي الستائر المركبة", f"{fmt_qty(total_sheet)} م²"),
        ("إجمالي ساعات التشغيل", f"{fmt_qty(total_hours)} ساعة"),
        ("أيام بملاحظات تربة/أعطال", str(issue_days)),
    ]
    box_w = 120
    y += 10
    for label, value in summary_rows:
        text(doc, right - box_w, y, box_w - 40, label, 8.5, "", MUTED, "R")
        text(doc, right - box_w, y, box_w, value, 8.5, "B", INK, "L")
        y += 6

    # certification
    y += 8
    if y > doc.h - 40:
        doc.add_page()
        y = 14
    text(doc, right - 160, y, 160, "نقرّ بأن أعمال الخوازيق/الستائر المنفذة مطابقة للمواصفات المعتمدة والرسومات التنفيذية، والكميات أعلاه حقيقية ومثبتة بصور وفحص الموقع.", 7, "", MUTED, "R")
    ty = y + 12
    half = (right - doc.l_margin) / 2 - 8
    text(doc, right - half, ty, half, "مهندس الموقع / المشرف", 8, "B", MUTED, "R")
    text(doc, doc.l_margin, ty, half, "استلام الاستشاري", 8, "B", MUTED, "R")
    doc.set_draw_color(*MUTED)
    doc.set_line_width(0.3)
    doc.line(right - half, ty + 13, right, ty + 13)
    doc.line(doc.l_margin, ty + 13, doc.l_margin + half, ty + 13)

    return bytes(doc.output())

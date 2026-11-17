"""Progress tracking: field logs vs contracted BOQ quantities of the latest quote.

Mapping (fixed, explicit):
- BOQ lines with norm_unit 'm'  and category 'drilling'  -> field metric depth_m
- BOQ lines with norm_unit 'm3' and category 'concrete'  -> field metric concrete_m3
- BOQ lines with norm_unit 'm2' and category 'sheet_pile'-> field metric sheet_pile_m2
Everything else is reported as "not field-trackable" (unit economics stay honest).
"""

from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DailyLog, Quote
from app.pricing import load_quote_lines

# In drilling & deep-foundation BOQs, units are unambiguous:
# every meter is a drilled meter, every m3 is poured, every m2 is driven sheets.
TRACKED_BY_UNIT = {
    "m": "depth_m",
    "m3": "concrete_m3",
    "m2": "sheet_pile_m2",
}


def _latest_quote(session: Session, project_id: int) -> Quote | None:
    stmt = (
        select(Quote)
        .where(Quote.project_id == project_id)
        .order_by(Quote.version.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def field_totals(session: Session, project_id: int) -> dict[str, Any]:
    row = session.execute(
        select(
            func.coalesce(func.sum(DailyLog.depth_m), 0),
            func.coalesce(func.sum(DailyLog.concrete_m3), 0),
            func.coalesce(func.sum(DailyLog.sheet_pile_m2), 0),
            func.coalesce(func.sum(DailyLog.operating_hours), 0),
            func.count(DailyLog.id),
        ).where(DailyLog.project_id == project_id)
    ).one()
    return {
        "depth_m": Decimal(str(row[0])),
        "concrete_m3": Decimal(str(row[1])),
        "sheet_pile_m2": Decimal(str(row[2])),
        "operating_hours": Decimal(str(row[3])),
        "logs_count": int(row[4]),
    }


def project_progress(session: Session, project_id: int) -> dict[str, Any] | None:
    quote = _latest_quote(session, project_id)
    if quote is None:
        return None

    totals = field_totals(session, project_id)
    lines = load_quote_lines(session, quote.id)

    tracked: list[dict[str, Any]] = []
    untracked: list[dict[str, Any]] = []
    earned = Decimal("0.00")
    tracked_value = Decimal("0.00")

    for row in lines:
        boq_qty = row["boq_qty"]
        contract_base = (boq_qty or Decimal("0")) * (row["boq_factor"] or Decimal("1"))
        key = row["norm_unit"]
        metric = TRACKED_BY_UNIT.get(key) if row["norm_unit"] else None

        if metric and contract_base > 0:
            actual = totals[metric]
            ratio = actual / contract_base if contract_base else Decimal("0")
            earned += row["line_total"] * min(ratio, Decimal("1"))
            tracked_value += row["line_total"]
            tracked.append({
                "code": row["code"],
                "description": row["description"],
                "contract_qty": contract_base,
                "contract_unit": row["norm_unit"],
                "actual": actual,
                "percent": float(ratio * 100),
                "value_total": row["line_total"],
                "value_earned": (row["line_total"] * min(ratio, Decimal("1"))).quantize(Decimal("0.01")),
            })
        else:
            untracked.append({
                "code": row["code"],
                "description": row["description"],
                "contract_qty": contract_base,
                "contract_unit": row["norm_unit"] or row["boq_unit"] or "",
                "value_total": row["line_total"],
                "reason": "لا يوجد مقياس ميداني لهذا البند",
            })

    overall = float((earned / tracked_value * 100) if tracked_value else Decimal("0"))
    return {
        "quote": quote,
        "lines": tracked,
        "untracked": untracked,
        "tracked_value": tracked_value,
        "earned": earned.quantize(Decimal("0.01")),
        "overall_percent": overall,
        "totals": totals,
    }

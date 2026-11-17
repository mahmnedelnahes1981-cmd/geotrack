"""As-built invoicing: executed field quantities x contracted unit rates.

Attribution rule (documented, predictable): aggregate field totals are
distributed to tracked lines of the same metric proportionally to their
contracted quantities; each tracked line's executed value = allocated qty x
the unit price from the accepted quote. Untracked lines (ls/piece/kg...) are
listed as excluded — nothing is billed that a rig didn't measurably do.
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.extract.units import normalize_unit
from app.models import AuditLog, Invoice, PriceListItem, Quote
from app.pricing import load_quote_lines, quote_code
from app.progress import field_totals

TWO_PLACES = Decimal("0.01")
TRACKED_BY_UNIT = {"m": "depth_m", "m3": "concrete_m3", "m2": "sheet_pile_m2"}


def _r2(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def convert_base_quantity(base_qty: Decimal, unit: str) -> Decimal:
    """base_qty (m/m3/kg...) -> the unit the price is expressed in."""
    info = normalize_unit(unit) if unit else None
    if info is None or not info.known:
        return base_qty
    if info.base_unit in ("m", "m3", "m2", "kg", "piece", "ls", "day", "l"):
        return base_qty / info.factor
    return base_qty


def _latest_quote(session: Session, project_id: int) -> Quote | None:
    stmt = (
        select(Quote)
        .where(Quote.project_id == project_id)
        .order_by(Quote.version.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


@dataclass
class InvoiceComputation:
    quote: Quote
    currency: str
    tax_rate: Decimal
    lines: list[dict[str, Any]] = field(default_factory=list)
    exclusions: list[dict[str, Any]] = field(default_factory=list)
    contract_value: Decimal = Decimal("0.00")
    executed_subtotal: Decimal = Decimal("0.00")
    executed_tax: Decimal = Decimal("0.00")
    executed_total: Decimal = Decimal("0.00")
    allocated: dict[str, Decimal] = field(default_factory=dict)   # metric -> allocated qty used


def compute_invoice(session: Session, project_id: int, tax_rate: Decimal) -> InvoiceComputation:
    quote = _latest_quote(session, project_id)
    if quote is None:
        raise ValueError("no quote for this project — generate one first")

    totals = field_totals(session, project_id)
    lines = load_quote_lines(session, quote.id)
    price_items = {p.id: p for p in session.scalars(select(PriceListItem))}

    # group tracked lines per metric, compute contract totals
    groups: dict[str, list[dict]] = {metric: [] for metric in TRACKED_BY_UNIT.values()}
    for row in lines:
        metric = TRACKED_BY_UNIT.get(row["norm_unit"] or "")
        contract_base = (row["boq_qty"] or Decimal("0")) * (row["boq_factor"] or Decimal("1"))
        if metric and contract_base > 0:
            groups[metric].append({**row, "contract_base": contract_base})

    computation = InvoiceComputation(quote=quote, currency=quote.currency, tax_rate=tax_rate)
    computation.contract_value = _r2(sum((row["line_total"] for row in lines), Decimal("0.00")))

    priced_codes: set[int] = set()
    for metric, group in groups.items():
        actual = totals[metric]
        contract_total = sum((row["contract_base"] for row in group), Decimal("0"))
        for row in group:
            share = (row["contract_base"] / contract_total) if contract_total else Decimal("0")
            exec_qty = actual * share
            price_item = price_items.get(row["line"].price_item_id)
            price_unit = price_item.unit if price_item else ""
            exec_in_price_unit = convert_base_quantity(exec_qty, price_unit or "")
            line_value = _r2(exec_in_price_unit * row["unit_price"])
            ratio = float(exec_qty / row["contract_base"] * 100) if row["contract_base"] else 0.0
            computation.lines.append({
                "code": row["code"],
                "description": row["description"],
                "metric": metric,
                "contract_qty": row["contract_base"],
                "executed_qty": _r2(exec_qty),
                "unit": price_unit or (row["norm_unit"] or ""),
                "unit_price": row["unit_price"],
                "executed_value": line_value,
                "ratio": ratio,
                "value_total": row["line_total"],
            })
            priced_codes.add(row["line"].id)
        computation.allocated[metric] = actual

    for row in lines:
        metric = TRACKED_BY_UNIT.get(row["norm_unit"] or "")
        contract_base = (row["boq_qty"] or Decimal("0")) * (row["boq_factor"] or Decimal("1"))
        if not (metric and contract_base > 0):
            computation.exclusions.append({
                "code": row["code"],
                "description": row["description"],
                "contract_value": str(row["line_total"]),
                "reason": "لا يوجد مقياس ميداني — يُفصَّل يدويًا أو بأمر تغيير",
            })

    computation.lines.sort(key=lambda l: l["code"])
    computation.executed_subtotal = _r2(sum((l["executed_value"] for l in computation.lines), Decimal("0.00")))
    computation.executed_tax = _r2(computation.executed_subtotal * tax_rate / Decimal("100"))
    computation.executed_total = _r2(computation.executed_subtotal + computation.executed_tax)
    return computation


def create_invoice(session: Session, project, tax_rate: Decimal) -> Invoice:
    computation = compute_invoice(session, project.id, tax_rate)
    invoice = Invoice(
        project_id=project.id,
        quote_id=computation.quote.id,
        invoice_number="GT-INV-PENDING",
        currency=computation.currency,
        tax_rate=tax_rate,
        contract_value=computation.contract_value,
        executed_subtotal=computation.executed_subtotal,
        executed_tax=computation.executed_tax,
        executed_total=computation.executed_total,
        totals_json={
            "quote_code": quote_code(computation.quote),
            "allocated": {k: str(v) for k, v in computation.allocated.items()},
            "lines": [
                {**{k: (str(v) if isinstance(v, Decimal) else v) for k, v in line.items()}}
                for line in computation.lines
            ],
            "exclusions": computation.exclusions,
        },
    )
    session.add(invoice)
    session.flush()
    invoice.invoice_number = f"GT-INV-{invoice.id:04d}"
    session.add(AuditLog(entity="invoice", entity_id=invoice.id, action="invoice_created",
                         diff_json={"executed_total": str(computation.executed_total),
                                    "quote_code": quote_code(computation.quote)}, actor="local-reviewer"))
    session.flush()
    return invoice

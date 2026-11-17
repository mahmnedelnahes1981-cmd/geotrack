"""Pricing engine: approved BOQ lines x active price list -> quote.

Unit strategy (deterministic, explicit):
- quantity_base = boq quantity x boq unit_factor  (e.g. ton x1000 -> kg)
- the price item's unit is parsed by the same normalizer
- compatible dimensions (both resolve to the same base unit) -> qty converted
  (qty_in_price_unit = quantity_base / price_unit_factor)
- unknown units: exact case-insensitive string match is accepted with factor 1
  and a loud warning; anything else is EXCLUDED from the quote with a reason.
Nothing is priced silently.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.extract.units import normalize_unit
from app.models import (
    AuditLog,
    BoqItem,
    BoqItemStatus,
    PriceList,
    PriceListItem,
    Quote,
    QuoteLine,
    QuoteStatus,
)

TWO_PLACES = Decimal("0.01")


def _r2(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def unit_price_from_item(item: PriceListItem) -> Decimal:
    base = item.material_cost + item.labor_cost + item.equipment_cost
    with_overhead = base * (Decimal("1") + item.overhead_pct / Decimal("100"))
    with_profit = with_overhead * (Decimal("1") + item.profit_pct / Decimal("100"))
    return _r2(with_profit)


def price_boq_quantity(
    item: BoqItem, price_item: PriceListItem
) -> tuple[Decimal | None, str | None]:
    """Return (qty expressed in the price item's unit, warning) or (None, reason)."""
    if item.quantity is None:
        return None, "missing quantity"

    boq_base = item.norm_unit
    qty_base = item.quantity * item.unit_factor

    price_unit_raw = (price_item.unit or "").strip()
    price_info = normalize_unit(price_unit_raw) if price_unit_raw else None

    if not boq_base:
        # extraction never recognized the boq unit: accept identical strings only
        raw = (item.unit or "").strip().lower()
        if price_unit_raw and raw and price_unit_raw.lower() == raw:
            return item.quantity, f"unit '{item.unit}' not recognized; assumed factor 1 — verify manually"
        return None, f"unrecognized boq unit '{item.unit}' — cannot price safely"

    if price_info is not None and price_info.known:
        if price_info.base_unit != boq_base:
            return None, f"unit mismatch: BOQ resolves to '{boq_base}', price item is '{price_unit_raw}'"
        return qty_base / price_info.factor, None

    # price unit not recognized: identical raw strings only, factor 1
    raw = (item.unit or "").strip().lower()
    if price_unit_raw and raw and price_unit_raw.lower() == raw:
        return qty_base, f"price unit '{price_unit_raw}' not recognized; assumed factor 1 — verify manually"
    return None, f"price item unit '{price_unit_raw or '?'}' not recognized"


@dataclass
class PricedLine:
    boq_item_id: int
    price_item_id: int
    code: str
    description: str
    qty: Decimal
    unit: str
    unit_price: Decimal
    line_total: Decimal


@dataclass
class QuoteComputation:
    price_list: PriceList
    currency: str
    tax_rate: Decimal
    lines: list[PricedLine] = field(default_factory=list)
    exclusions: list[dict[str, Any]] = field(default_factory=list)
    subtotal: Decimal = Decimal("0.00")
    tax: Decimal = Decimal("0.00")
    grand_total: Decimal = Decimal("0.00")


def compute_quote(
    session: Session,
    document_id: int,
    tax_rate: Decimal,
    price_list: PriceList | None = None,
) -> QuoteComputation:
    stmt = select(PriceList).where(PriceList.is_active.is_(True)).order_by(PriceList.id.desc()).limit(1)
    pl = price_list or session.scalars(stmt).first()
    if pl is None:
        raise ValueError("no active price list — seed one first (scripts/seed_price_list.py)")

    eligible = list(session.scalars(
        select(BoqItem).where(
            BoqItem.document_id == document_id,
            BoqItem.status.in_([BoqItemStatus.approved, BoqItemStatus.edited]),
            BoqItem.suggested_price_item_id.is_not(None),
        ).order_by(BoqItem.id)
    ))

    price_items = {p.id: p for p in session.scalars(select(PriceListItem))}
    computation = QuoteComputation(price_list=pl, currency=pl.currency, tax_rate=tax_rate)

    for item in eligible:
        price_item = price_items.get(item.suggested_price_item_id)
        if price_item is None:
            computation.exclusions.append({"boq_item_id": item.id, "reason": "suggested price item not found"})
            continue
        if price_item.price_list_id != pl.id:
            computation.exclusions.append(
                {"boq_item_id": item.id, "reason": f"price item belongs to a different list (id {price_item.price_list_id})"})
            continue
        qty, warning = price_boq_quantity(item, price_item)
        if qty is None:
            computation.exclusions.append({"boq_item_id": item.id, "code": price_item.code, "reason": warning})
            continue
        unit_price = unit_price_from_item(price_item)
        line_total = _r2(qty * unit_price)
        computation.lines.append(PricedLine(
            boq_item_id=item.id, price_item_id=price_item.id, code=price_item.code,
            description=item.norm_description or item.raw_description,
            qty=_r2(qty), unit=price_item.unit or (item.norm_unit or ""),
            unit_price=unit_price, line_total=line_total,
        ))

    computation.subtotal = _r2(sum((l.line_total for l in computation.lines), Decimal("0.00")))
    computation.tax = _r2(computation.subtotal * tax_rate / Decimal("100"))
    computation.grand_total = _r2(computation.subtotal + computation.tax)
    return computation


def create_quote(
    session: Session,
    document,
    tax_rate: Decimal,
) -> Quote:
    """Persist a new quote version for (project, boq_source_document)."""
    computation = compute_quote(session, document.id, tax_rate)

    existing_max = session.scalars(
        select(func.max(Quote.version)).where(
            Quote.project_id == document.project_id,
            Quote.boq_source_document_id == document.id,
        )
    ).one()
    version = (existing_max or 0) + 1

    quote = Quote(
        project_id=document.project_id,
        boq_source_document_id=document.id,
        price_list_id=computation.price_list.id,
        status=QuoteStatus.draft,
        currency=computation.currency,
        tax_rate=tax_rate,
        version=version,
        totals_json={
            "subtotal": str(computation.subtotal),
            "tax": str(computation.tax),
            "tax_rate": str(tax_rate),
            "grand_total": str(computation.grand_total),
            "line_count": len(computation.lines),
            "exclusions": computation.exclusions,
        },
    )
    session.add(quote)
    session.flush()

    for line in computation.lines:
        session.add(QuoteLine(
            quote_id=quote.id, boq_item_id=line.boq_item_id, price_item_id=line.price_item_id,
            qty=line.qty, unit_price=line.unit_price, line_total=line.line_total,
        ))
    session.add(AuditLog(
        entity="quote", entity_id=quote.id, action="quote_created",
        diff_json={"version": version, "grand_total": str(computation.grand_total),
                   "exclusions": computation.exclusions},
        actor="system",
    ))
    session.flush()
    return quote


def recompute_quote_tax(session: Session, quote: Quote, tax_rate: Decimal) -> Quote:
    """Tax-only recalculation — lines are untouched."""
    subtotal = sum((l.line_total for l in quote.lines), Decimal("0.00"))
    subtotal_r2 = _r2(subtotal)
    tax = _r2(subtotal_r2 * tax_rate / Decimal("100"))
    grand = _r2(subtotal_r2 + tax)
    quote.tax_rate = tax_rate
    totals = dict(quote.totals_json or {})
    totals.update({"subtotal": str(subtotal_r2), "tax": str(tax),
                   "tax_rate": str(tax_rate), "grand_total": str(grand)})
    quote.totals_json = totals
    session.add(AuditLog(entity="quote", entity_id=quote.id, action="tax_updated",
                         diff_json={"tax_rate": str(tax_rate), "grand_total": str(grand)}, actor="local-reviewer"))
    session.flush()
    return quote


def quote_code(quote: Quote) -> str:
    return f"GT-{quote.id:04d}-v{quote.version}"


def load_quote_lines(session: Session, quote_id: int) -> list[dict]:
    """Lines joined with boq + price item for display/PDF."""
    rows = session.execute(
        select(QuoteLine, BoqItem, PriceListItem)
        .join(BoqItem, QuoteLine.boq_item_id == BoqItem.id)
        .join(PriceListItem, QuoteLine.price_item_id == PriceListItem.id)
        .where(QuoteLine.quote_id == quote_id)
        .order_by(QuoteLine.id)
    ).all()
    lines = []
    for line, boq, price in rows:
        lines.append({
            "line": line,
            "code": price.code,
            "unit": price.unit or boq.norm_unit or "",
            "description": boq.norm_description or boq.raw_description,
            "qty": line.qty,
            "unit_price": line.unit_price,
            "line_total": line.line_total,
            # contract side (BOQ, not price-normalized) — used by progress tracking
            "boq_qty": boq.quantity,
            "boq_unit": boq.unit,
            "boq_factor": boq.unit_factor,
            "norm_unit": boq.norm_unit,
            "norm_category": boq.norm_category,
        })
    return lines

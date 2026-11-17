"""Pricing engine tests. Expected numbers are computed by hand below."""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import BoqItem, BoqItemStatus, PriceList, PriceListItem, Quote
from app.pricing import (
    compute_quote,
    create_quote,
    load_quote_lines,
    price_boq_quantity,
    quote_code,
    recompute_quote_tax,
    unit_price_from_item,
)
from app.seed import seed_price_list
from app.services import ingest_file

from conftest import FIXTURES


@pytest.fixture
def session(tmp_path):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    seed_price_list(sess)
    sess.commit()
    yield sess
    sess.close()


def _prepare_document(session, tmp_path, approve_indexes=(0, 1, 2, 3, 4, 5)):
    from app.models import Project

    project = Project(name="Test Project", status="new")
    session.add(project)
    session.flush()
    document, _ = ingest_file(session, FIXTURES / "boq_en_micropiles.xlsx",
                              storage_dir=tmp_path, project_id=project.id)
    items = session.scalars(
        select(BoqItem).where(BoqItem.document_id == document.id).order_by(BoqItem.id)
    ).all()
    codes = ["DRL.MIC.200", "REINF.CAGE.150", "CON.C30", "SHT.DRV.18", "DRL.JET.600", "MOB.001"]
    price_items = {p.code: p for p in session.scalars(select(PriceListItem))}
    for idx, code in enumerate(codes):
        if idx in approve_indexes:
            items[idx].status = BoqItemStatus.approved
            items[idx].suggested_price_item_id = price_items[code].id
    session.commit()
    return document, items


def test_unit_price_formula(session):
    p = session.scalars(select(PriceListItem).where(PriceListItem.code == "DRL.MIC.200")).one()
    # (8+35+40) * 1.1 * 1.15 = 83 * 1.265 = 104.995 -> 105.00 (ROUND_HALF_UP)
    assert unit_price_from_item(p) == Decimal("105.00")


def test_ton_to_kg_conversion_uses_unit_factor(session, tmp_path):
    _, items = _prepare_document(session, tmp_path)
    cage = items[1]
    price_item = session.scalars(select(PriceListItem).where(PriceListItem.code == "REINF.CAGE.150")).one()
    qty_in_price_unit, warning = price_boq_quantity(cage, price_item)
    assert warning is None
    assert qty_in_price_unit == Decimal("12500")   # 12.5 ton x1000 -> kg


def test_compute_quote_hand_verified(session, tmp_path):
    document, _ = _prepare_document(session, tmp_path)
    computation = compute_quote(session, document.id, Decimal("14"))

    assert len(computation.lines) == 6
    assert computation.exclusions == []

    # lines in insertion order: DRL 89,250.00 | REINF 34,750.00 | CON 15,180.48 | SHT 53,130.00 | JET 351,045.00 | MOB ?
    totals = {line.code: line.line_total for line in computation.lines}
    assert totals["DRL.MIC.200"] == Decimal("89250.00")   # 850 * 105.00
    assert totals["REINF.CAGE.150"] == Decimal("34750.00")  # 12500 * 2.78
    assert totals["CON.C30"] == Decimal("15180.48")         # 96 * 158.13
    assert totals["SHT.DRV.18"] == Decimal("53130.00")      # 420 * 126.50
    assert totals["DRL.JET.600"] == Decimal("351045.00")    # 1500 * 234.03
    # MOB.001: ls, qty 1, (2000+500+800)*1.1*1.12 = 3300*1.232 = 4065.60
    assert totals["MOB.001"] == Decimal("4065.60")

    assert computation.subtotal == sum(totals.values()).quantize(Decimal("0.01"))
    expected_subtotal = Decimal("89250.00") + Decimal("34750.00") + Decimal("15180.48") \
        + Decimal("53130.00") + Decimal("351045.00") + Decimal("4065.60")
    assert computation.subtotal == expected_subtotal
    assert computation.tax == (expected_subtotal * Decimal("0.14")).quantize(Decimal("0.01"))
    assert computation.grand_total == computation.subtotal + computation.tax


def test_unit_mismatch_excludes_with_reason(session, tmp_path):
    document, items = _prepare_document(session, tmp_path)
    price_items = {p.code: p for p in session.scalars(select(PriceListItem))}
    # force an impossible pairing: sheet pile price unit m2 vs steel kg order
    items[1].suggested_price_item_id = price_items["SHT.DRV.18"].id   # kg line vs m2 price
    session.commit()

    computation = compute_quote(session, document.id, Decimal("14"))
    assert len(computation.lines) == 5
    assert len(computation.exclusions) == 1
    assert computation.exclusions[0]["code"] == "SHT.DRV.18"
    assert "mismatch" in computation.exclusions[0]["reason"]


def test_unknown_identical_unit_accepted_with_warning(session, tmp_path):
    document, _ = ingest_file(session, FIXTURES / "boq_unknown_units.xlsx", storage_dir=tmp_path)
    price_list = session.scalars(select(PriceList)).one()
    weird = PriceListItem(price_list_id=price_list.id, code="TST.LOAD", description="Static load test",
                          unit="test", material_cost=Decimal("1500"), labor_cost=Decimal("300"),
                          equipment_cost=Decimal("0"), overhead_pct=Decimal("0"), profit_pct=Decimal("0"))
    session.add(weird)
    session.flush()

    items = session.scalars(select(BoqItem).order_by(BoqItem.id)).all()
    items[0].status = BoqItemStatus.approved
    items[0].suggested_price_item_id = weird.id
    session.commit()

    computation = compute_quote(session, document.id, Decimal("14"))
    assert len(computation.lines) == 1
    qty, warning = price_boq_quantity(items[0], weird)
    assert qty == Decimal("2")
    assert warning and "assumed factor 1" in warning


def test_create_quote_versions_and_totals(session, tmp_path):
    document, _ = _prepare_document(session, tmp_path)
    quote1 = create_quote(session, document, Decimal("14"))
    quote2 = create_quote(session, document, Decimal("14"))
    session.commit()

    assert quote1.version == 1
    assert quote2.version == 2
    assert quote_code(quote2) == f"GT-{quote2.id:04d}-v2"

    lines = load_quote_lines(session, quote1.id)
    assert len(lines) == 6
    subtotal_from_lines = sum(l["line_total"] for l in lines)
    assert Decimal(quote1.totals_json["subtotal"]) == subtotal_from_lines


def test_recompute_quote_tax_keeps_lines(session, tmp_path):
    document, _ = _prepare_document(session, tmp_path)
    quote = create_quote(session, document, Decimal("14"))
    session.commit()
    original_grand = Decimal(quote.totals_json["grand_total"])

    recompute_quote_tax(session, quote, Decimal("15"))
    session.commit()

    subtotal = Decimal(quote.totals_json["subtotal"])
    assert Decimal(quote.totals_json["tax"]) == (subtotal * Decimal("0.15")).quantize(Decimal("0.01"))
    assert Decimal(quote.totals_json["grand_total"]) == subtotal + Decimal(quote.totals_json["tax"])
    assert Decimal(quote.totals_json["grand_total"]) != original_grand
    # lines were not rebuilt
    assert len(load_quote_lines(session, quote.id)) == 6

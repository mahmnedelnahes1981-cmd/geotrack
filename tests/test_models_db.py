"""Round-trip test: create schema in memory, persist a document + BOQ item
with a suggested price item, and read them back."""

from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import BoqItem, BoqItemStatus, Document, DocumentKind, PriceList, PriceListItem


def test_suggested_price_item_roundtrip():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    price_list = PriceList(name="Standard", version="2026.1", currency="USD")
    session.add(price_list)
    session.flush()

    price_item = PriceListItem(
        price_list_id=price_list.id,
        code="MIC.DRL.200",
        description="Drilling micropiles Ø200mm",
        unit="m",
        material_cost=Decimal("0"),
        labor_cost=Decimal("45"),
        equipment_cost=Decimal("60"),
    )
    document = Document(
        kind=DocumentKind.xlsx,
        original_name="boq.xlsx",
        sha256="0" * 64,
        storage_path="/tmp/boq.xlsx",
    )
    session.add_all([price_item, document])
    session.flush()

    item = BoqItem(
        document_id=document.id,
        line_no=1,
        raw_description="حفر خوازيق دقيقة قطر ٢٠٠ مم",
        quantity=Decimal("850"),
        unit="م",
        norm_unit="m",
        unit_factor=Decimal("1"),
        confidence=Decimal("0.90"),
        suggested_price_item_id=price_item.id,
    )
    session.add(item)
    session.commit()

    fetched = session.query(BoqItem).one()
    assert fetched.status == BoqItemStatus.proposed
    assert fetched.suggested_price_item.code == "MIC.DRL.200"
    assert fetched.suggested_price_item.equipment_cost == Decimal("60")
    assert fetched.document.kind is DocumentKind.xlsx

    session.close()

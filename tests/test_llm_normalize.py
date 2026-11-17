"""LLM normalization pass, tested with a fake LLM (no network, no Ollama needed)."""

import json
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.llm.normalize import normalize_document
from app.models import BoqItem, PriceList, PriceListItem
from app.services import ingest_file

from conftest import FIXTURES


class FakeLLM:
    def __init__(self, content: str):
        self.content = content
        self.calls = 0

    def complete(self, system: str, user: str):
        self.calls += 1
        return self.content, {"usage": {"total_tokens": 42}, "model": "fake", "system_seen": system, "user_seen": user}


@pytest.fixture
def session(tmp_path):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    price_list = PriceList(name="Standard", version="2026.1", currency="USD", is_active=True)
    sess.add(price_list)
    sess.flush()
    sess.add_all([
        PriceListItem(price_list_id=price_list.id, code="MIC.DRL.200",
                      description="Drilling micropiles 200mm", unit="m", category="drilling",
                      material_cost=Decimal("10"), labor_cost=Decimal("45"), equipment_cost=Decimal("60")),
        PriceListItem(price_list_id=price_list.id, code="CON.C30",
                      description="Concrete C30/37", unit="m3", category="concrete",
                      material_cost=Decimal("90"), labor_cost=Decimal("20"), equipment_cost=Decimal("5")),
    ])
    sess.commit()
    yield sess
    sess.close()


def _ingest(session, tmp_path):
    document, _ = ingest_file(session, FIXTURES / "boq_en_micropiles.xlsx", storage_dir=tmp_path)
    items = session.scalars(select(BoqItem).where(BoqItem.document_id == document.id).order_by(BoqItem.id)).all()
    return document, items


def _payload(items) -> str:
    return json.dumps({"items": items}, ensure_ascii=False)


def test_normalize_applies_fields_and_matches_catalog(session, tmp_path):
    document, items = _ingest(session, tmp_path)
    det_conf_0 = items[0].confidence
    fake = FakeLLM(_payload([
        {"line_id": items[0].id, "norm_description": "Drilling micropiles Ø200mm, depth 12m",
         "norm_category": "drilling", "suggested_code": "MIC.DRL.200", "confidence": 0.95},
        {"line_id": items[2].id, "norm_description": "Micropile concrete C30/37",
         "norm_category": "concrete", "suggested_code": "CON.C30", "confidence": 0.30},
    ]))

    summary = normalize_document(session, document.id, client=fake)
    assert fake.calls == 1
    assert summary["updated"] == 2
    assert summary["suggested"] == 2
    assert summary["error"] is None

    session.expire_all()
    items = session.scalars(select(BoqItem).where(BoqItem.document_id == document.id).order_by(BoqItem.id)).all()
    assert items[0].norm_description == "Drilling micropiles Ø200mm, depth 12m"
    assert items[0].norm_category == "drilling"
    assert items[0].suggested_price_item_id is not None
    assert items[0].confidence == det_conf_0                # min(0.90 det, 0.95 llm) = 0.90
    assert items[2].confidence == Decimal("0.30")           # min(0.90 det, 0.30 llm) = 0.30 -> human review

    price_item = session.get(PriceListItem, items[0].suggested_price_item_id)
    assert price_item.code == "MIC.DRL.200"

    document = session.get(type(document), document.id)
    assert document.llm_raw_response["content"]          # raw response persisted for audit
    assert document.llm_raw_response["response"]["usage"]["total_tokens"] == 42


def test_unknown_suggested_code_is_dropped_not_forced(session, tmp_path):
    document, items = _ingest(session, tmp_path)
    fake = FakeLLM(_payload([
        {"line_id": items[0].id, "norm_description": "Micropile drilling Ø200mm",
         "norm_category": "drilling", "suggested_code": "DOES.NOT.EXIST", "confidence": 0.9},
    ]))
    summary = normalize_document(session, document.id, client=fake)
    assert summary["suggested"] == 0
    assert summary["updated"] == 1
    session.expire_all()
    item = session.scalars(select(BoqItem).where(BoqItem.id == items[0].id)).one()
    assert item.suggested_price_item_id is None


def test_markdown_fenced_json_is_accepted(session, tmp_path):
    document, items = _ingest(session, tmp_path)
    raw = "```json\n" + _payload([
        {"line_id": items[0].id, "norm_description": "Drilling micropiles",
         "norm_category": "drilling", "confidence": 0.88},
    ]) + "\n```"
    summary = normalize_document(session, document.id, client=FakeLLM(raw))
    assert summary["updated"] == 1


def test_garbage_output_never_corrupts_items(session, tmp_path):
    document, items = _ingest(session, tmp_path)
    summary = normalize_document(session, document.id, client=FakeLLM("this is not json {{{"))
    assert summary["updated"] == 0
    assert summary["error"]
    session.expire_all()
    for item in session.scalars(select(BoqItem).where(BoqItem.document_id == document.id)):
        assert item.norm_description is None
    document = session.get(type(document), document.id)
    assert document.llm_raw_response["content"] == "this is not json {{{"


def test_hallucinated_line_ids_are_ignored(session, tmp_path):
    document, items = _ingest(session, tmp_path)
    summary = normalize_document(session, document.id, client=FakeLLM(_payload([
        {"line_id": 999999, "norm_description": "Bogus line", "confidence": 0.99},
    ])))
    assert summary["updated"] == 0
    assert 999999 in summary["skipped"]


def test_items_not_returned_by_llm_stay_untouched(session, tmp_path):
    document, items = _ingest(session, tmp_path)
    summary = normalize_document(session, document.id, client=FakeLLM(_payload([
        {"line_id": items[0].id, "norm_description": "Drilling micropiles only", "confidence": 0.9},
    ])))
    assert summary["updated"] == 1
    session.expire_all()
    remaining = session.scalars(
        select(BoqItem).where(BoqItem.document_id == document.id, BoqItem.id != items[0].id)
    ).all()
    assert all(i.norm_description is None for i in remaining)

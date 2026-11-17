"""Quote UI flow: generate from review, view, tax edit, PDF download, errors."""

import re
from decimal import Decimal

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import BoqItem, BoqItemStatus, PriceListItem, Project, Quote
from app.seed import seed_price_list

from conftest import FIXTURES


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        sess = TestingSession()
        try:
            yield sess
        finally:
            sess.close()

    app.dependency_overrides[get_db] = override_get_db
    seed_session = TestingSession()
    seed_price_list(seed_session)
    seed_session.commit()
    seed_session.close()

    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))

    yield TestClient(app), TestingSession

    app.dependency_overrides.clear()


def _upload_xlsx(client, new_project_name="مشروع تسعير") -> int:
    with open(FIXTURES / "boq_en_micropiles.xlsx", "rb") as fh:
        payload = fh.read()
    response = client.post(
        "/upload",
        files={"file": ("boq_en_micropiles.xlsx", payload)},
        data={"project_id": "", "new_project_name": new_project_name, "run_llm": ""},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return int(re.search(r"/documents/(\d+)/review", response.headers["location"]).group(1))


def _approve_items(TestingSession, doc_id):
    sess = TestingSession()
    items = sess.scalars(select(BoqItem).where(BoqItem.document_id == doc_id).order_by(BoqItem.id)).all()
    codes = ["DRL.MIC.200", "REINF.CAGE.150", "CON.C30", "SHT.DRV.18", "DRL.JET.600", "MOB.001"]
    price_items = {p.code: p for p in sess.scalars(select(PriceListItem))}
    for idx, code in enumerate(codes):
        items[idx].status = BoqItemStatus.approved
        items[idx].suggested_price_item_id = price_items[code].id
    sess.commit()
    sess.close()


def test_generate_quote_view_and_pdf(env):
    client, TestingSession = env
    doc_id = _upload_xlsx(client)
    _approve_items(TestingSession, doc_id)

    response = client.post(f"/documents/{doc_id}/quote", follow_redirects=False)
    assert response.status_code == 303
    assert "/quotes/" in response.headers["location"]

    quote_page = client.get(response.headers["location"])
    assert quote_page.status_code == 200
    assert "الإجمالي شامل الضريبة" in quote_page.text
    assert "GT-" in quote_page.text
    assert "DRL.MIC.200" in quote_page.text

    pdf = client.get(response.headers["location"] + "/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:5] == b"%PDF-"

    sess = TestingSession()
    quote = sess.scalars(select(Quote)).one()
    assert quote.pdf_path and quote.pdf_path.endswith(".pdf")
    assert quote.totals_json["line_count"] == 6
    sess.close()


def test_generate_quote_requires_project(env):
    client, TestingSession = env
    with open(FIXTURES / "boq_en_micropiles.xlsx", "rb") as fh:
        payload = fh.read()
    response = client.post(
        "/upload",
        files={"file": ("boq_en_micropiles.xlsx", payload)},
        data={"project_id": "", "new_project_name": "", "run_llm": ""},
        follow_redirects=False,
    )
    doc_id = int(re.search(r"/documents/(\d+)/review", response.headers["location"]).group(1))
    blocked = client.post(f"/documents/{doc_id}/quote", follow_redirects=False)
    assert blocked.status_code == 303
    assert "quote_error=needs_project" in blocked.headers["location"]


def test_set_project_then_quote_created(env):
    client, TestingSession = env
    with open(FIXTURES / "boq_en_micropiles.xlsx", "rb") as fh:
        payload = fh.read()
    response = client.post(
        "/upload",
        files={"file": ("boq_en_micropiles.xlsx", payload)},
        data={"project_id": "", "new_project_name": "", "run_llm": ""},
        follow_redirects=False,
    )
    doc_id = int(re.search(r"/documents/(\d+)/review", response.headers["location"]).group(1))
    _approve_items(TestingSession, doc_id)

    linked = client.post(
        f"/documents/{doc_id}/set-project",
        data={"project_id": "", "new_project_name": "مشروع يعمل تلقائياً"},
        follow_redirects=False,
    )
    assert linked.status_code == 303
    assert "/quotes/" in linked.headers["location"]

    sess = TestingSession()
    project = sess.scalars(select(Project).where(Project.name == "مشروع يعمل تلقائياً")).one()
    assert project is not None
    quote = sess.scalars(select(Quote)).one()
    assert quote.project_id == project.id
    sess.close()


def test_tax_update_recomputes_grand_total(env):
    client, TestingSession = env
    doc_id = _upload_xlsx(client)
    _approve_items(TestingSession, doc_id)
    response = client.post(f"/documents/{doc_id}/quote", follow_redirects=False)
    quote_url = response.headers["location"]

    sess = TestingSession()
    quote = sess.scalars(select(Quote)).one()
    subtotal = Decimal(quote.totals_json["subtotal"])
    grand_14 = Decimal(quote.totals_json["grand_total"])
    sess.close()

    client.post(quote_url + "/tax", data={"tax_rate": "15"}, follow_redirects=False)

    sess = TestingSession()
    quote = sess.scalars(select(Quote)).one()
    assert quote.tax_rate == Decimal("15.00") or quote.tax_rate == Decimal("15")
    assert Decimal(quote.totals_json["tax"]) == (subtotal * Decimal("0.15")).quantize(Decimal("0.01"))
    assert Decimal(quote.totals_json["grand_total"]) != grand_14
    sess.close()

    page = client.get(quote_url)
    assert "الضريبة (15.00%)" in page.text or "الضريبة (15%)" in page.text

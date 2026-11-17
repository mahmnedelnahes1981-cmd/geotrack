"""Phase 3 — handover: invoice engine, PDFs, completion flow, dashboard."""

import re
from decimal import Decimal

import pdfplumber
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.invoicing import compute_invoice, create_invoice
from app.main import app
from app.models import (BoqItem, BoqItemStatus, DailyLog, Invoice, PriceListItem,
                        Project, Quote, QuoteStatus, Rig)
from app.seed import seed_price_list
from app.services import ingest_file

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
    seed_session.add(Rig(code="DRL-001", name="Test drill", kind="micropile_drill", status="available"))
    seed_session.commit()
    seed_session.close()

    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))

    yield TestClient(app), TestingSession

    app.dependency_overrides.clear()


def _make_quote(TestingSession, tmp_path, with_logs=True):
    sess = TestingSession()
    project = Project(name="مشروع اختبار التسليم", status="in_progress")
    sess.add(project)
    sess.flush()
    document, _ = ingest_file(sess, FIXTURES / "boq_ar_micropiles.pdf",
                              storage_dir=tmp_path / "up", project_id=project.id)
    items = sess.scalars(
        select(BoqItem).where(BoqItem.document_id == document.id).order_by(BoqItem.id)
    ).all()
    codes = ["DRL.MIC.200", "REINF.CAGE.150", "CON.C30", "SHT.DRV.18", "MOB.001"]
    price_items = {p.code: p for p in sess.scalars(select(PriceListItem))}
    for idx, code in enumerate(codes):
        items[idx].status = BoqItemStatus.approved
        items[idx].suggested_price_item_id = price_items[code].id
    sess.commit()
    from app.pricing import create_quote
    quote = create_quote(sess, document, Decimal("14"))
    if with_logs:
        for offset, (depth, conc, sheet) in enumerate(((425, 96, 210),)):
            sess.add(DailyLog(project_id=project.id, depth_m=Decimal(str(depth)),
                              concrete_m3=Decimal(str(conc)), sheet_pile_m2=Decimal(str(sheet)),
                              operating_hours=Decimal("20"), log_date=__import__("datetime").date.today(),
                              pile_id="P-01", recorded_by="tester"))
    sess.commit()
    project_id = project.id
    quote_id = quote.id
    sess.close()
    return quote_id, project_id


def test_invoice_math_hand_verified(env, tmp_path):
    client, TestingSession = env
    _, project_id = _make_quote(TestingSession, tmp_path)

    sess = TestingSession()
    computation = compute_invoice(sess, project_id, Decimal("14"))
    by_code = {l["code"]: l for l in computation.lines}

    # DRL.MIC.200: 425 m x 105.00 = 44,625.00
    assert by_code["DRL.MIC.200"]["executed_value"] == Decimal("44625.00")
    # CON.C30: 96 m3 x 158.13 = 15,180.48
    assert by_code["CON.C30"]["executed_value"] == Decimal("15180.48")
    # SHT.DRV.18: 210 m2 x 126.50 = 26,565.00
    assert by_code["SHT.DRV.18"]["executed_value"] == Decimal("26565.00")

    assert computation.executed_subtotal == Decimal("86370.48")
    assert computation.executed_tax == Decimal("12091.87")
    assert computation.executed_total == Decimal("98462.35")
    assert computation.contract_value == Decimal("196376.08")

    excluded = {e["code"] for e in computation.exclusions}
    assert "REINF.CAGE.150" in excluded
    assert "MOB.001" in excluded
    sess.close()


def test_invoice_create_and_pdf_routes(env, tmp_path):
    client, TestingSession = env
    _, project_id = _make_quote(TestingSession, tmp_path)

    response = client.post(f"/projects/{project_id}/invoice", follow_redirects=False)
    assert response.status_code == 303
    invoice_url = response.headers["location"]

    sess = TestingSession()
    invoice = sess.scalars(select(Invoice)).one()
    assert invoice.invoice_number == f"GT-INV-{invoice.id:04d}"
    assert invoice.quote_id is not None
    sess.close()

    page = client.get(invoice_url)
    assert page.status_code == 200
    assert "فاتورة ختامية" in page.text
    assert invoice.invoice_number in page.text

    pdf = client.get(invoice_url + "/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:5] == b"%PDF-"


def test_report_pdf_route(env, tmp_path):
    client, TestingSession = env
    _, project_id = _make_quote(TestingSession, tmp_path)
    response = client.get(f"/projects/{project_id}/report.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    report_path = tmp_path / "report.pdf"
    report_path.write_bytes(response.content)
    with pdfplumber.open(report_path) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    assert "AS-BUILT" in text


def test_complete_releases_rig_and_reopen(env, tmp_path):
    client, TestingSession = env
    _, project_id = _make_quote(TestingSession, tmp_path)

    sess = TestingSession()
    rig_id = sess.scalars(select(Rig).where(Rig.code == "DRL-001")).one().id
    sess.close()
    client.post(f"/projects/{project_id}/assign-rig", data={"rig_id": str(rig_id)}, follow_redirects=False)

    client.post(f"/projects/{project_id}/complete", follow_redirects=False)
    sess = TestingSession()
    project = sess.get(Project, project_id)
    assert project.status == "completed"
    assert project.rig_id is None
    assert sess.get(Rig, rig_id).status == "available"
    sess.close()

    client.post(f"/projects/{project_id}/reopen", follow_redirects=False)
    sess = TestingSession()
    assert sess.get(Project, project_id).status == "in_progress"
    sess.close()


def test_invoice_requires_quote(env, tmp_path):
    client, TestingSession = env
    sess = TestingSession()
    project = Project(name="مشروع بلا عرض", status="new")
    sess.add(project)
    sess.commit()
    project_id = project.id
    sess.close()

    response = client.post(f"/projects/{project_id}/invoice", follow_redirects=False)
    assert response.status_code == 303
    assert "invoice_error=no_quote" in response.headers["location"]


def test_dashboard_renders_with_stats(env, tmp_path):
    client, TestingSession = env
    _, project_id = _make_quote(TestingSession, tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "لوحة التحكم" in response.text
    assert "مشروع اختبار التسليم" in response.text

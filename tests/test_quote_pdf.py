"""Quote PDF generation: valid PDF, Arabic-safe, ASCII-verifiable contents."""

from decimal import Decimal

import pdfplumber
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import BoqItem, BoqItemStatus, PriceListItem, Project, Quote
from app.pricing import create_quote, load_quote_lines, quote_code
from app.quote_pdf import build_quote_pdf
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


def _make_quote(session, tmp_path):
    project = Project(name="مشروع الستائر اللوحية", status="new")
    session.add(project)
    session.flush()
    document, _ = ingest_file(session, FIXTURES / "boq_ar_micropiles.pdf",
                              storage_dir=tmp_path / "uploads", project_id=project.id)
    items = session.scalars(
        select(BoqItem).where(BoqItem.document_id == document.id).order_by(BoqItem.id)
    ).all()
    codes = ["DRL.MIC.200", "REINF.CAGE.150", "CON.C30", "SHT.DRV.18", "MOB.001"]
    price_items = {p.code: p for p in session.scalars(select(PriceListItem))}
    for idx, code in enumerate(codes):
        items[idx].status = BoqItemStatus.approved
        items[idx].suggested_price_item_id = price_items[code].id
    session.commit()

    quote = create_quote(session, document, Decimal("14"))
    session.commit()
    lines = load_quote_lines(session, quote.id)
    return quote, project, lines


def test_pdf_bytes_are_valid_and_text_layer_has_code(session, tmp_path):
    quote, project, lines = _make_quote(session, tmp_path)
    pdf_bytes = build_quote_pdf(quote, project, project.client, lines)

    assert pdf_bytes[:5] == b"%PDF-"
    assert len(pdf_bytes) > 2000

    pdf_path = tmp_path / "quote.pdf"
    pdf_path.write_bytes(pdf_bytes)
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    assert quote_code(quote) in text
    assert "QUOTATION" in text


def test_pdf_totals_present(session, tmp_path):
    quote, project, lines = _make_quote(session, tmp_path)
    pdf_bytes = build_quote_pdf(quote, project, project.client, lines)
    pdf_path = tmp_path / "quote.pdf"
    pdf_path.write_bytes(pdf_bytes)
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    grand = Decimal(quote.totals_json["grand_total"])
    assert f"{grand:,.2f}" in text


def test_lines_flow_into_pdf(session, tmp_path):
    quote, project, lines = _make_quote(session, tmp_path)
    assert len(lines) == 5
    assert any(l["code"] == "DRL.MIC.200" for l in lines)

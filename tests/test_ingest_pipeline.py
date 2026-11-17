"""End-to-end ingestion: file on disk -> Document + proposed BoqItems."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import BoqItem, DocumentKind, DocumentStatus
from app.services import ingest_file

from conftest import FIXTURES


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield sess
    sess.close()


def test_ingest_en_xlsx(session, tmp_path):
    document, summary = ingest_file(session, FIXTURES / "boq_en_micropiles.xlsx", storage_dir=tmp_path)
    assert document.kind is DocumentKind.xlsx
    assert document.status is DocumentStatus.extracted
    assert summary["items"] == 6
    assert len(document.sha256) == 64
    assert (tmp_path / f"{document.sha256}.xlsx").exists()

    items = session.scalars(select(BoqItem).order_by(BoqItem.id)).all()
    assert len(items) == 6
    assert all(i.status.value == "proposed" for i in items)
    assert items[0].source_ref == "BOQ!R2"
    assert items[0].quantity is not None


def test_ingest_en_pdf_sets_source_page(session, tmp_path):
    document, summary = ingest_file(session, FIXTURES / "boq_en_micropiles.pdf", storage_dir=tmp_path)
    assert document.kind is DocumentKind.pdf_text
    assert summary["items"] == 6
    items = session.scalars(select(BoqItem)).all()
    assert all(i.source_page == 1 for i in items)


def test_ingest_csv(session, tmp_path):
    document, summary = ingest_file(session, FIXTURES / "boq_en.csv", storage_dir=tmp_path)
    assert document.kind is DocumentKind.csv
    assert summary["items"] == 4


def test_ingest_scanned_pdf_extracts_nothing_but_survives(session, tmp_path):
    document, summary = ingest_file(session, FIXTURES / "boq_blank_scanned.pdf", storage_dir=tmp_path)
    assert document.status is DocumentStatus.extracted
    assert summary["items"] == 0
    assert any("text layer" in w for w in summary["warnings"])


def test_ingest_rejects_unsupported_type(session, tmp_path):
    bogus = tmp_path / "notes.docx"
    bogus.write_text("not supported", encoding="utf-8")
    with pytest.raises(ValueError):
        ingest_file(session, bogus, storage_dir=tmp_path)

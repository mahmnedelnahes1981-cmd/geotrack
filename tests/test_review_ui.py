"""UI workflow tests: upload -> review -> approve/reject/edit/reset."""

import re
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import BoqItem, BoqItemStatus, PriceListItem
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
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))

    yield TestClient(app), TestingSession

    app.dependency_overrides.clear()


def _upload_fixture(client, filename="boq_en_micropiles.xlsx", data=None):
    with open(FIXTURES / filename, "rb") as fh:
        payload = fh.read()
    return client.post("/upload", files={"file": (filename, payload)}, data=data or {}, follow_redirects=False)


def _review_url_from_redirect(response) -> tuple[str, int]:
    location = response.headers["location"]
    match = re.search(r"/documents/(\d+)/review", location)
    assert match, location
    return location, int(match.group(1))


def test_upload_form_renders(env):
    client, _ = env
    response = client.get("/upload")
    assert response.status_code == 200
    assert "رفع ملف المقايسة" in response.text


def test_upload_xlsx_creates_document_and_redirects(env):
    client, TestingSession = env
    response = _upload_fixture(client, data={"project_id": "", "new_project_name": "مشروع اختبار", "run_llm": ""})
    assert response.status_code == 303
    location, doc_id = _review_url_from_redirect(response)

    sess = TestingSession()
    assert len(sess.scalars(select(BoqItem)).all()) == 6
    sess.close()

    review = client.get(location)
    assert review.status_code == 200
    assert "Drilling micropiles" in review.text
    assert "boq_en_micropiles.xlsx" in review.text


def test_approve_reject_reset_flow(env):
    client, TestingSession = env
    _, doc_id = _review_url_from_redirect(_upload_fixture(client, data={"project_id": "", "new_project_name": "", "run_llm": ""}))

    sess = TestingSession()
    item = sess.scalars(select(BoqItem).order_by(BoqItem.id)).first()
    item_id = item.id
    sess.close()

    resp = client.post(f"/documents/{doc_id}/items/{item_id}/approve")
    assert resp.status_code == 200
    assert "status-pill-approved" in resp.text

    sess = TestingSession()
    assert sess.get(BoqItem, item_id).status is BoqItemStatus.approved
    assert sess.get(BoqItem, item_id).reviewed_at is not None
    sess.close()

    resp = client.post(f"/documents/{doc_id}/items/{item_id}/reject")
    assert "status-pill-rejected" in resp.text

    resp = client.post(f"/documents/{doc_id}/items/{item_id}/reset")
    assert "status-pill-proposed" in resp.text
    sess = TestingSession()
    assert sess.get(BoqItem, item_id).status is BoqItemStatus.proposed
    sess.close()


def test_update_quantity_inline_marks_edited(env):
    client, TestingSession = env
    _, doc_id = _review_url_from_redirect(_upload_fixture(client, data={"project_id": "", "new_project_name": "", "run_llm": ""}))

    sess = TestingSession()
    item = sess.scalars(select(BoqItem).order_by(BoqItem.id)).first()
    item_id = item.id
    sess.close()

    resp = client.post(
        f"/documents/{doc_id}/items/{item_id}/update",
        data={"quantity": "999", "unit": "m", "unit_factor": "1",
              "norm_description": "", "norm_category": "", "suggested_price_item_id": ""},
    )
    assert resp.status_code == 200

    sess = TestingSession()
    updated = sess.get(BoqItem, item_id)
    assert updated.quantity == Decimal("999")
    assert updated.status is BoqItemStatus.edited
    sess.close()


def test_suggestion_assignment_does_not_flag_edited(env):
    client, TestingSession = env
    _, doc_id = _review_url_from_redirect(_upload_fixture(client, data={"project_id": "", "new_project_name": "", "run_llm": ""}))

    sess = TestingSession()
    item = sess.scalars(select(BoqItem).order_by(BoqItem.id)).first()
    item_id = item.id
    price_item = sess.scalars(select(PriceListItem).where(PriceListItem.code == "DRL.MIC.200")).one()
    sess.close()

    resp = client.post(
        f"/documents/{doc_id}/items/{item_id}/update",
        data={"quantity": "850", "unit": "m", "unit_factor": "1",
              "norm_description": "", "norm_category": "",
              "suggested_price_item_id": str(price_item.id)},
    )
    assert resp.status_code == 200

    sess = TestingSession()
    updated = sess.get(BoqItem, item_id)
    assert updated.suggested_price_item_id == price_item.id
    assert updated.status is BoqItemStatus.proposed
    sess.close()


def test_review_page_htmx_urls_include_document_id(env):
    client, _ = env
    _, doc_id = _review_url_from_redirect(_upload_fixture(client, data={"project_id": "", "new_project_name": "", "run_llm": ""}))
    response = client.get(f"/documents/{doc_id}/review")
    assert f"/documents/{doc_id}/items/" in response.text
    assert "/documents//items/" not in response.text


def test_documents_list_and_review_page_render(env):
    client, _ = env
    _upload_fixture(client, data={"project_id": "", "new_project_name": "مشروع القائمة", "run_llm": ""})
    response = client.get("/documents")
    assert response.status_code == 200
    assert "boq_en_micropiles.xlsx" in response.text
    assert "فتح المراجعة" in response.text

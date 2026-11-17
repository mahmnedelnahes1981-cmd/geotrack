"""Phase 2 — field operations: rigs, accept flow, sync endpoint, progress."""

import re
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import BoqItem, BoqItemStatus, DailyLog, PriceListItem, Project, Quote, QuoteStatus, Rig
from app.pricing import create_quote
from app.progress import project_progress
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
    seed_session.add_all([
        Rig(code="DRL-001", name="Test drill", kind="micropile_drill", status="available"),
        Rig(code="SHE-001", name="Test driver", kind="sheet_pile_driver", status="available"),
        Rig(code="EXC-009", name="Broken excavator", kind="excavator", status="maintenance"),
    ])
    seed_session.commit()
    seed_session.close()

    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))

    yield TestClient(app), TestingSession

    app.dependency_overrides.clear()


def _make_quote(TestingSession, tmp_path, with_project=True):
    sess = TestingSession()
    project = Project(name="مشروع اختبار التنفيذ", status="new") if with_project else None
    if project:
        sess.add(project)
        sess.flush()
    document, _ = ingest_file(sess, FIXTURES / "boq_ar_micropiles.pdf",
                              storage_dir=tmp_path / "up", project_id=(project.id if project else None))
    items = sess.scalars(
        select(BoqItem).where(BoqItem.document_id == document.id).order_by(BoqItem.id)
    ).all()
    codes = ["DRL.MIC.200", "REINF.CAGE.150", "CON.C30", "SHT.DRV.18", "MOB.001"]
    price_items = {p.code: p for p in sess.scalars(select(PriceListItem))}
    for idx, code in enumerate(codes):
        items[idx].status = BoqItemStatus.approved
        items[idx].suggested_price_item_id = price_items[code].id
    sess.commit()
    quote = create_quote(sess, document, Decimal("14"))
    sess.commit()
    quote_id = quote.id
    project_id = project.id if project else None
    sess.close()
    return quote_id, project_id


def test_accept_quote_marks_project_in_progress(env, tmp_path):
    client, TestingSession = env
    quote_id, project_id = _make_quote(TestingSession, tmp_path)

    response = client.post(f"/quotes/{quote_id}/accept", follow_redirects=False)
    assert response.status_code == 303
    assert f"/projects/{project_id}" in response.headers["location"]

    sess = TestingSession()
    assert sess.get(Quote, quote_id).status is QuoteStatus.accepted
    assert sess.get(Project, project_id).status == "in_progress"
    sess.close()


def test_assign_and_unassign_rig(env, tmp_path):
    client, TestingSession = env
    _, project_id = _make_quote(TestingSession, tmp_path)

    sess = TestingSession()
    rig_id = sess.scalars(select(Rig).where(Rig.code == "DRL-001")).one().id
    sess.close()

    client.post(f"/projects/{project_id}/assign-rig", data={"rig_id": str(rig_id)}, follow_redirects=False)
    sess = TestingSession()
    assert sess.get(Project, project_id).rig_id == rig_id
    assert sess.get(Rig, rig_id).status == "assigned"
    sess.close()

    client.post(f"/projects/{project_id}/unassign-rig", follow_redirects=False)
    sess = TestingSession()
    assert sess.get(Project, project_id).rig_id is None
    assert sess.get(Rig, rig_id).status == "available"
    sess.close()


def test_maintenance_rig_cannot_be_assigned(env, tmp_path):
    client, TestingSession = env
    _, project_id = _make_quote(TestingSession, tmp_path)

    sess = TestingSession()
    maintenance_id = sess.scalars(select(Rig).where(Rig.code == "EXC-009")).one().id
    sess.close()

    response = client.post(f"/projects/{project_id}/assign-rig",
                           data={"rig_id": str(maintenance_id)}, follow_redirects=False)
    assert "rig_error=maintenance" in response.headers["location"]
    sess = TestingSession()
    assert sess.get(Project, project_id).rig_id is None
    sess.close()


def test_sync_creates_logs_and_dedupes(env, tmp_path):
    client, TestingSession = env
    _, project_id = _make_quote(TestingSession, tmp_path)

    entries = [
        {"client_uuid": "uuid-test-0001", "log_date": date.today().isoformat(),
         "pile_id": "P-77", "depth_m": 8.5, "concrete_m3": 3.2, "operating_hours": 8, "recorded_by": "tester"},
        {"client_uuid": "uuid-test-0002", "log_date": date.today().isoformat(),
         "depth_m": 0, "concrete_m3": 0, "sheet_pile_m2": 40, "operating_hours": 4},
    ]
    response = client.post(f"/api/projects/{project_id}/logs/sync", json={"logs": entries})
    assert response.status_code == 200
    body = response.json()
    assert body["synced"] == 2
    assert body["errors"] == 0

    again = client.post(f"/api/projects/{project_id}/logs/sync", json={"logs": entries})
    again_body = again.json()
    assert again_body["synced"] == 0
    assert again_body["duplicates"] == 2

    sess = TestingSession()
    assert sess.scalar(select(func.count(DailyLog.id)).where(DailyLog.project_id == project_id)) == 2
    assert sess.scalar(select(func.count(DailyLog.id)).where(DailyLog.created_offline.is_(True))) == 2
    sess.close()


def test_sync_rejects_negative_quantities(env, tmp_path):
    client, TestingSession = env
    _, project_id = _make_quote(TestingSession, tmp_path)

    entries = [{"client_uuid": "uuid-neg-0001", "log_date": date.today().isoformat(),
                "depth_m": -5, "concrete_m3": 0, "operating_hours": 0}]
    response = client.post(f"/api/projects/{project_id}/logs/sync", json={"logs": entries})
    body = response.json()
    assert body["errors"] == 1
    assert body["synced"] == 0

    sess = TestingSession()
    assert sess.scalar(select(func.count(DailyLog.id))) == 0
    sess.close()


def test_sync_rejects_unknown_rig(env, tmp_path):
    client, TestingSession = env
    _, project_id = _make_quote(TestingSession, tmp_path)

    entries = [{"client_uuid": "uuid-rig-0001", "log_date": date.today().isoformat(),
                "rig_id": 9999, "depth_m": 1}]
    response = client.post(f"/api/projects/{project_id}/logs/sync", json={"logs": entries})
    assert response.json()["errors"] == 1


def test_progress_math_tracked_and_untracked(env, tmp_path):
    client, TestingSession = env
    quote_id, project_id = _make_quote(TestingSession, tmp_path)

    entries = [
        {"client_uuid": "uuid-prog-0001", "log_date": date.today().isoformat(),
         "depth_m": 425, "concrete_m3": 96, "sheet_pile_m2": 210, "operating_hours": 20},
    ]
    client.post(f"/api/projects/{project_id}/logs/sync", json={"logs": entries})

    sess = TestingSession()
    progress = project_progress(sess, project_id)
    by_code = {line["code"]: line for line in progress["lines"]}
    assert by_code["DRL.MIC.200"]["percent"] == pytest.approx(50.0, abs=0.01)   # 425/850
    assert by_code["CON.C30"]["percent"] == pytest.approx(100.0, abs=0.01)      # 96/96
    assert by_code["SHT.DRV.18"]["percent"] == pytest.approx(50.0, abs=0.01)    # 210/420
    assert progress["overall_percent"] > 0
    assert progress["overall_percent"] < 100
    untracked_codes = {u["code"] for u in progress["untracked"]}
    # reinforcement (kg) and mobilization (ls) have no field metric
    assert "REINF.CAGE.150" in untracked_codes
    assert "MOB.001" in untracked_codes
    assert progress["totals"]["depth_m"] == Decimal("425.00")
    sess.close()


def test_field_page_and_project_page_render(env, tmp_path):
    client, TestingSession = env
    quote_id, project_id = _make_quote(TestingSession, tmp_path)

    field_page = client.get(f"/projects/{project_id}/field")
    assert field_page.status_code == 200
    assert "شغل النهاردة" in field_page.text

    project_page = client.get(f"/projects/{project_id}")
    assert project_page.status_code == 200
    assert "التنفيذ الفعلي مقابل المقايسة" in project_page.text
    assert "شاشة سواق الحفار" in project_page.text

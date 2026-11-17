"""Field operations: offline-first daily drilling log + batch sync endpoint."""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import PACKAGE_DIR
from app.db import get_db
from app.models import DailyLog, Project, Rig

router = APIRouter()
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))


@router.get("/projects/{project_id}/field", response_class=HTMLResponse)
def field_log_page(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        return HTMLResponse("project not found", status_code=404)

    rigs = db.scalars(select(Rig).order_by(Rig.code)).all()
    project_rig = db.get(Rig, project.rig_id) if project.rig_id else None

    recent_logs = db.scalars(
        select(DailyLog).where(DailyLog.project_id == project_id)
        .order_by(DailyLog.log_date.desc(), DailyLog.id.desc()).limit(15)
    ).all()

    return templates.TemplateResponse(request, "field_log.html", {
        "project": project,
        "rigs": rigs,
        "project_rig": project_rig,
        "recent_logs": recent_logs,
        "today": date.today().isoformat(),
    })


class LogEntry(BaseModel):
    client_uuid: str = Field(min_length=8, max_length=64)
    log_date: date
    rig_id: int | None = None
    pile_id: str | None = Field(default=None, max_length=64)
    depth_m: Decimal = Decimal("0")
    concrete_m3: Decimal = Decimal("0")
    sheet_pile_m2: Decimal = Decimal("0")
    operating_hours: Decimal = Decimal("0")
    soil_notes: str | None = None
    breakdown_notes: str | None = None
    remarks: str | None = None
    recorded_by: str | None = Field(default=None, max_length=120)
    created_offline: bool = True


class LogBatch(BaseModel):
    logs: list[LogEntry]


def _non_negative(*values: Decimal) -> bool:
    return all(v >= 0 for v in values)


@router.post("/api/projects/{project_id}/logs/sync")
def sync_logs(project_id: int, batch: LogBatch, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    results = []
    synced = duplicates = errors = 0

    for entry in batch.logs:
        if not _non_negative(entry.depth_m, entry.concrete_m3, entry.sheet_pile_m2, entry.operating_hours):
            errors += 1
            results.append({"client_uuid": entry.client_uuid, "status": "error", "detail": "negative quantity"})
            continue
        if entry.rig_id is not None and db.get(Rig, entry.rig_id) is None:
            errors += 1
            results.append({"client_uuid": entry.client_uuid, "status": "error", "detail": f"rig {entry.rig_id} not found"})
            continue

        existing = db.scalars(select(DailyLog).where(DailyLog.client_uuid == entry.client_uuid)).first()
        if existing is not None:
            duplicates += 1
            results.append({"client_uuid": entry.client_uuid, "status": "duplicate"})
            continue

        db.add(DailyLog(
            project_id=project_id,
            rig_id=entry.rig_id,
            log_date=entry.log_date,
            pile_id=(entry.pile_id or None),
            depth_m=entry.depth_m,
            concrete_m3=entry.concrete_m3,
            sheet_pile_m2=entry.sheet_pile_m2,
            operating_hours=entry.operating_hours,
            soil_notes=entry.soil_notes or None,
            breakdown_notes=entry.breakdown_notes or None,
            remarks=entry.remarks or None,
            recorded_by=entry.recorded_by or None,
            client_uuid=entry.client_uuid,
            created_offline=entry.created_offline,
        ))
        synced += 1
        results.append({"client_uuid": entry.client_uuid, "status": "synced"})

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="sync commit failed")

    return JSONResponse({"results": results, "synced": synced, "duplicates": duplicates, "errors": errors})

"""Projects & rigs: project hub, rig assignment, list pages."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.config import PACKAGE_DIR
from app.db import get_db
from app.models import Client, DailyLog, Document, Project, Quote, Rig, BoqItem, BoqItemStatus
from app.pricing import quote_code
from app.progress import project_progress

router = APIRouter()
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))

STATUS_AR = {"new": "جديد", "in_progress": "قيد التنفيذ", "completed": "مكتمل", "on_hold": "معلّق"}
RIG_KIND_AR = {"micropile_drill": "حفار خوازيق دقيقة", "sheet_pile_driver": "دق ستائر لوحية",
               "crane": "ونش", "excavator": "حفار عام", "other": "أخرى"}
RIG_STATUS_AR = {"available": "متاح", "assigned": "مخصص", "maintenance": "صيانة"}


@router.get("/projects", response_class=HTMLResponse)
def projects_list(request: Request, db: Session = Depends(get_db)):
    projects = db.scalars(select(Project).order_by(Project.created_at.desc())).all()
    rows = []
    for project in projects:
        latest_quote = db.scalars(
            select(Quote).where(Quote.project_id == project.id)
            .order_by(Quote.version.desc()).limit(1)
        ).first()
        client = db.get(Client, project.client_id) if project.client_id else None
        rig = db.get(Rig, project.rig_id) if project.rig_id else None
        rows.append({"project": project, "latest_quote": latest_quote, "client": client, "rig": rig})
    return templates.TemplateResponse(request, "projects.html",
                                      {"rows": rows, "status_ar": STATUS_AR, "rig_kind_ar": RIG_KIND_AR})


@router.get("/rigs", response_class=HTMLResponse)
def rigs_page(request: Request, db: Session = Depends(get_db)):
    rigs = db.scalars(select(Rig).order_by(Rig.code)).all()
    return templates.TemplateResponse(request, "rigs.html",
                                      {"rigs": rigs, "rig_kind_ar": RIG_KIND_AR, "rig_status_ar": RIG_STATUS_AR})


@router.post("/rigs")
def add_rig(request: Request,
            code: str = Form(...),
            name: str = Form(...),
            kind: str = Form("micropile_drill"),
            notes: str = Form(""),
            db: Session = Depends(get_db)):
    rig = Rig(code=code.strip().upper(), name=name.strip(), kind=kind, notes=notes.strip() or None)
    db.add(rig)
    try:
        db.commit()
    except Exception:
        db.rollback()
        rigs = db.scalars(select(Rig).order_by(Rig.code)).all()
        return templates.TemplateResponse(
            request, "rigs.html",
            {"rigs": rigs, "rig_kind_ar": RIG_KIND_AR, "rig_status_ar": RIG_STATUS_AR,
             "error": f"الكود {code.strip().upper()} مستخدم بالفعل"},
            status_code=400,
        )
    return RedirectResponse("/rigs", status_code=303)


@router.get("/projects/{project_id}", response_class=HTMLResponse)
def project_page(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        return HTMLResponse("project not found", status_code=404)

    client = db.get(Client, project.client_id) if project.client_id else None
    rig = db.get(Rig, project.rig_id) if project.rig_id else None
    assignable_rigs = db.scalars(
        select(Rig).where(Rig.status != "maintenance").order_by(Rig.code)
    ).all()

    latest_quote = db.scalars(
        select(Quote).where(Quote.project_id == project_id)
        .order_by(Quote.version.desc()).limit(1)
    ).first()
    accepted = any(q.status.value == "accepted" for q in db.scalars(
        select(Quote).where(Quote.project_id == project_id)))

    progress = project_progress(db, project_id)

    from app.models import Invoice
    latest_invoice = db.scalars(
        select(Invoice).where(Invoice.project_id == project_id)
        .order_by(Invoice.id.desc()).limit(1)
    ).first()
    logs_count = db.scalar(select(func.count(DailyLog.id)).where(DailyLog.project_id == project_id)) or 0

    recent_logs = db.scalars(
        select(DailyLog).where(DailyLog.project_id == project_id)
        .order_by(DailyLog.log_date.desc(), DailyLog.id.desc()).limit(10)
    ).all()

    documents = db.scalars(
        select(Document).where(Document.project_id == project_id)
        .order_by(Document.uploaded_at.desc())
    ).all()

    return templates.TemplateResponse(request, "project.html", {
        "project": project,
        "client": client,
        "rig": rig,
        "assignable_rigs": assignable_rigs,
        "latest_quote": latest_quote,
        "latest_quote_code": quote_code(latest_quote) if latest_quote else None,
        "any_accepted": accepted,
        "latest_invoice": latest_invoice,
        "logs_count": logs_count,
        "progress": progress,
        "recent_logs": recent_logs,
        "documents": documents,
        "status_ar": STATUS_AR,
        "rig_kind_ar": RIG_KIND_AR,
        "rig_status_ar": RIG_STATUS_AR,
    })


@router.post("/projects/{project_id}/assign-rig")
def assign_rig(project_id: int, rig_id: int = Form(...), db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    rig = db.get(Rig, rig_id)
    if project is None or rig is None:
        raise HTTPException(status_code=404)
    if rig.status == "maintenance":
        return RedirectResponse(f"/projects/{project_id}?rig_error=maintenance", status_code=303)
    # release current assignment
    if project.rig_id and project.rig_id != rig.id:
        old_rig = db.get(Rig, project.rig_id)
        if old_rig:
            old_rig.status = "available"
    project.rig_id = rig.id
    rig.status = "assigned"
    db.commit()
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/unassign-rig")
def unassign_rig(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404)
    if project.rig_id:
        rig = db.get(Rig, project.rig_id)
        if rig:
            rig.status = "available"
        project.rig_id = None
        db.commit()
    return RedirectResponse(f"/projects/{project_id}", status_code=303)

"""Phase 3 — handover: final invoice, as-built report PDF, project completion."""

from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BASE_DIR, get_settings
from app.db import get_db
from app.invoicing import create_invoice
from app.models import AuditLog, Client, Document, Invoice, Project, Quote, Rig
from app.pricing import quote_code
from app.report_pdf import build_report_pdf

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def _latest_quote(session: Session, project_id: int) -> Quote | None:
    stmt = (
        select(Quote)
        .where(Quote.project_id == project_id)
        .order_by(Quote.version.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


@router.post("/projects/{project_id}/invoice")
def generate_invoice(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404)
    settings = get_settings()
    try:
        invoice = create_invoice(db, project, Decimal(str(settings.quote_tax_rate)))
        db.commit()
    except ValueError:
        db.rollback()
        return RedirectResponse(f"/projects/{project_id}?invoice_error=no_quote", status_code=303)
    return RedirectResponse(f"/invoices/{invoice.id}", status_code=303)


def _invoice_view_lines(totals_json: dict) -> list[dict]:
    lines = []
    for raw in (totals_json or {}).get("lines", []):
        lines.append({
            "code": raw.get("code"),
            "description": raw.get("description"),
            "metric": raw.get("metric"),
            "contract_qty": Decimal(str(raw.get("contract_qty", "0"))),
            "executed_qty": Decimal(str(raw.get("executed_qty", "0"))),
            "unit": raw.get("unit"),
            "unit_price": Decimal(str(raw.get("unit_price", "0"))),
            "executed_value": Decimal(str(raw.get("executed_value", "0"))),
            "ratio": float(raw.get("ratio", 0) or 0),
            "value_total": Decimal(str(raw.get("value_total", "0"))),
        })
    return lines


@router.get("/invoices/{invoice_id}", response_class=HTMLResponse)
def invoice_page(invoice_id: int, request: Request, db: Session = Depends(get_db)):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        return HTMLResponse("invoice not found", status_code=404)
    project = db.get(Project, invoice.project_id)
    client = db.get(Client, project.client_id) if (project and project.client_id) else None
    document = db.get(Document, invoice.quote.boq_source_document_id) if (invoice.quote and invoice.quote.boq_source_document_id) else None
    siblings = db.scalars(
        select(Invoice).where(Invoice.project_id == invoice.project_id).order_by(Invoice.id)
    ).all()

    totals = invoice.totals_json or {}
    return templates.TemplateResponse(request, "invoice.html", {
        "invoice": invoice,
        "project": project,
        "client": client,
        "document": document,
        "lines": _invoice_view_lines(totals),
        "exclusions": totals.get("exclusions", []),
        "quote_code": totals.get("quote_code"),
        "siblings": siblings,
    })


@router.get("/invoices/{invoice_id}/pdf")
def invoice_pdf(invoice_id: int, db: Session = Depends(get_db)):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404)
    project = db.get(Project, invoice.project_id)
    client = db.get(Client, project.client_id) if (project and project.client_id) else None

    from app.invoice_pdf import build_invoice_pdf
    totals = invoice.totals_json or {}
    pdf_bytes = build_invoice_pdf(invoice, project, client, _invoice_view_lines(totals), totals)

    settings = get_settings()
    invoices_dir = Path(settings.upload_dir).parent / "invoices"
    invoices_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = invoices_dir / f"{invoice.invoice_number}.pdf"
    pdf_path.write_bytes(pdf_bytes)
    invoice.pdf_path = str(pdf_path)
    db.commit()
    return FileResponse(pdf_path, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{invoice.invoice_number}.pdf"'})


@router.post("/projects/{project_id}/complete")
def complete_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404)
    if project.rig_id:
        rig = db.get(Rig, project.rig_id)
        if rig:
            rig.status = "available"
        project.rig_id = None
    project.status = "completed"
    db.add(AuditLog(entity="project", entity_id=project.id, action="project_completed",
                    diff_json={"at": "handover"}, actor="local-reviewer"))
    db.commit()
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/reopen")
def reopen_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404)
    project.status = "in_progress"
    db.add(AuditLog(entity="project", entity_id=project.id, action="project_reopened",
                    diff_json={}, actor="local-reviewer"))
    db.commit()
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.get("/projects/{project_id}/report.pdf")
def as_built_report(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404)
    client = db.get(Client, project.client_id) if project.client_id else None
    rig = db.get(Rig, project.rig_id) if project.rig_id else None
    quote = _latest_quote(db, project_id)

    pdf_bytes = build_report_pdf(db, project, client, rig, quote_code(quote) if quote else None)

    from fastapi.responses import Response
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="as-built-report-GT-{project.id:04d}.pdf"'},
    )

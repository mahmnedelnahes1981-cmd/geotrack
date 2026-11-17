"""Quote routes: generate from review, view, tax tweak, PDF download."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BASE_DIR, get_settings
from app.db import get_db
from app.models import Document, PriceList, Project, Quote, QuoteStatus, AuditLog
from app.pricing import create_quote, load_quote_lines, quote_code, recompute_quote_tax
from app.quote_pdf import build_quote_pdf

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def _quote_error_redirect(document_id: int, code: str) -> RedirectResponse:
    return RedirectResponse(f"/documents/{document_id}/review?quote_error={code}", status_code=303)


@router.post("/documents/{document_id}/quote")
def generate_quote(document_id: int, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if document is None:
        return HTMLResponse("document not found", status_code=404)
    if document.project_id is None:
        return _quote_error_redirect(document_id, "needs_project")

    settings = get_settings()
    try:
        quote = create_quote(db, document, Decimal(str(settings.quote_tax_rate)))
        db.commit()
    except ValueError:
        db.rollback()
        return _quote_error_redirect(document_id, "no_price_list")
    return RedirectResponse(f"/quotes/{quote.id}", status_code=303)


@router.post("/documents/{document_id}/set-project")
def set_project_and_quote(
    document_id: int,
    project_id: str = Form(""),
    new_project_name: str = Form(""),
    db: Session = Depends(get_db),
):
    document = db.get(Document, document_id)
    if document is None:
        return HTMLResponse("document not found", status_code=404)

    resolved: int | None = int(project_id) if project_id else None
    if new_project_name.strip():
        project = Project(name=new_project_name.strip(), status="new")
        db.add(project)
        db.flush()
        resolved = project.id
    if resolved is None:
        return _quote_error_redirect(document_id, "project_required")

    document.project_id = resolved
    db.flush()
    settings = get_settings()
    try:
        quote = create_quote(db, document, Decimal(str(settings.quote_tax_rate)))
        db.commit()
    except ValueError:
        db.rollback()
        return _quote_error_redirect(document_id, "no_price_list")
    return RedirectResponse(f"/quotes/{quote.id}", status_code=303)


@router.get("/quotes/{quote_id}", response_class=HTMLResponse)
def quote_page(quote_id: int, request: Request, db: Session = Depends(get_db)):
    quote = db.get(Quote, quote_id)
    if quote is None:
        return HTMLResponse("quote not found", status_code=404)

    document = db.get(Document, quote.boq_source_document_id) if quote.boq_source_document_id else None
    project = db.get(Project, quote.project_id)
    client = project.client if (project and project.client) else None
    lines = load_quote_lines(db, quote.id)

    # other versions of the same quote series (same source document + project)
    siblings = db.scalars(
        select(Quote)
        .where(Quote.boq_source_document_id == quote.boq_source_document_id,
               Quote.project_id == quote.project_id)
        .order_by(Quote.version)
    ).all()
    eligible = len(lines)
    price_list = db.get(PriceList, quote.price_list_id) if quote.price_list_id else None

    return templates.TemplateResponse(request, "quote.html", {
        "quote": quote,
        "code": quote_code(quote),
        "document": document,
        "project": project,
        "client": client,
        "price_list": price_list,
        "lines": lines,
        "siblings": siblings,
        "eligible": eligible,
        "exclusions": (quote.totals_json or {}).get("exclusions", []),
        "subtotal": Decimal((quote.totals_json or {}).get("subtotal", "0")),
        "tax": Decimal((quote.totals_json or {}).get("tax", "0")),
        "grand_total": Decimal((quote.totals_json or {}).get("grand_total", "0")),
        "now": datetime.now(),
    })


@router.post("/quotes/{quote_id}/accept")
def accept_quote(quote_id: int, db: Session = Depends(get_db)):
    quote = db.get(Quote, quote_id)
    if quote is None:
        return HTMLResponse("quote not found", status_code=404)
    quote.status = QuoteStatus.accepted
    project = db.get(Project, quote.project_id)
    if project is not None:
        project.status = "in_progress"
    db.add(AuditLog(entity="quote", entity_id=quote.id, action="quote_accepted",
                    diff_json={"project_id": quote.project_id}, actor="local-reviewer"))
    db.commit()
    return RedirectResponse(f"/projects/{quote.project_id}", status_code=303)


@router.post("/quotes/{quote_id}/tax")
def update_tax(quote_id: int, tax_rate: str = Form(...), db: Session = Depends(get_db)):
    quote = db.get(Quote, quote_id)
    if quote is None:
        return HTMLResponse("quote not found", status_code=404)
    try:
        rate = Decimal(tax_rate.strip())
        if rate < 0 or rate > 100:
            raise InvalidOperation
    except InvalidOperation:
        return RedirectResponse(f"/quotes/{quote_id}?tax_error=1", status_code=303)
    recompute_quote_tax(db, quote, rate)
    db.commit()
    return RedirectResponse(f"/quotes/{quote_id}", status_code=303)


@router.get("/quotes/{quote_id}/pdf")
def download_pdf(quote_id: int, db: Session = Depends(get_db)):
    quote = db.get(Quote, quote_id)
    if quote is None:
        return HTMLResponse("quote not found", status_code=404)

    settings = get_settings()
    quotes_dir = Path(settings.upload_dir).parent / "quotes"
    quotes_dir.mkdir(parents=True, exist_ok=True)
    code = quote_code(quote)
    pdf_path = quotes_dir / f"{code}.pdf"

    document = db.get(Document, quote.boq_source_document_id) if quote.boq_source_document_id else None
    project = db.get(Project, quote.project_id) if quote.project_id else None
    client = project.client if (project and project.client) else None
    lines = load_quote_lines(db, quote.id)

    pdf_bytes = build_quote_pdf(quote, project, client, lines)
    pdf_path.write_bytes(pdf_bytes)
    quote.pdf_path = str(pdf_path)
    db.commit()

    return FileResponse(pdf_path, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{code}.pdf"'})

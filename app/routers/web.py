"""Review UI: upload BOQ -> deterministic extraction -> human approval workflow."""

import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import BASE_DIR, get_settings
from app.db import get_db
from app.models import (
    AuditLog,
    BoqItem,
    BoqItemStatus,
    Document,
    DocumentStatus,
    PriceList,
    PriceListItem,
    Project,
)
from app.services import ingest_file

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

CATEGORIES: list[tuple[str, str]] = [
    ("drilling", "حفر"),
    ("reinforcement", "تسليح"),
    ("concrete", "خرسانة"),
    ("steel", "حدادة / ستيل"),
    ("excavation", "حفر عام"),
    ("sheet_pile", "ستائر لوحية"),
    ("jet_grout", "جيت جروت"),
    ("mobilization", "تحريك معدات"),
    ("testing", "اختبارات"),
    ("other", "أخرى"),
]

STATUS_AR = {
    "proposed": "بانتظار المراجعة",
    "approved": "معتمد",
    "rejected": "مرفوض",
    "edited": "معدّل — يحتاج مراجعة",
}

def _actor() -> str:
    return "local-reviewer"  # real auth lands with multi-user support

def _active_price_items(db: Session) -> list[PriceListItem]:
    stmt = (
        select(PriceListItem)
        .join(PriceList, PriceListItem.price_list_id == PriceList.id)
        .where(PriceList.is_active.is_(True))
        .order_by(PriceListItem.category, PriceListItem.code)
    )
    return list(db.scalars(stmt))

def _price_units_map(items: list[PriceListItem]) -> dict[int, str | None]:
    return {i.id: i.unit for i in items}

def _suggestion_mismatch(item: BoqItem, unit_map: dict[int, str | None]) -> bool:
    if item.suggested_price_item_id is None:
        return False
    suggested_unit = unit_map.get(item.suggested_price_item_id)
    if not suggested_unit or not item.norm_unit:
        return False
    return suggested_unit != item.norm_unit

def _row_context(db: Session, document_id: int, item: BoqItem) -> dict:
    suggestions = _active_price_items(db)
    unit_map = _price_units_map(suggestions)
    return {
        "request": None,  # filled by caller when rendering a full response
        "document_id": document_id,
        "item": item,
        "suggestions": suggestions,
        "categories": CATEGORIES,
        "status_ar": STATUS_AR,
        "suggestion_mismatch": _suggestion_mismatch(item, unit_map),
    }

def _render_row(request: Request, db: Session, document_id: int, item_id: int) -> HTMLResponse:
    item = _get_item_or_404(db, item_id)
    ctx = _row_context(db, document_id, item)
    ctx["request"] = request
    return templates.TemplateResponse(request, "partials/item_row.html", ctx)

def _counts(db: Session, document_id: int) -> dict[str, int]:
    rows = db.execute(
        select(BoqItem.status, func.count(BoqItem.id))
        .where(BoqItem.document_id == document_id)
        .group_by(BoqItem.status)
    ).all()
    counts = {status.value: n for status, n in rows}
    counts["total"] = sum(counts.values())
    counts.setdefault("proposed", 0)
    counts.setdefault("approved", 0)
    counts.setdefault("rejected", 0)
    counts.setdefault("edited", 0)
    return counts

def _get_item_or_404(db: Session, item_id: int) -> BoqItem:
    item = db.get(BoqItem, item_id)
    if item is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="item not found")
    return item


def _audit(db: Session, item: BoqItem, action: str, diff: dict) -> None:
    db.add(AuditLog(entity="boq_item", entity_id=item.id, action=action,
                    diff_json=diff, actor=_actor()))

@router.get("/", response_class=HTMLResponse)
def root(request: Request, db: Session = Depends(get_db)):
    from app.models import Client, Invoice, Project, Quote, Rig, DailyLog
    from app.pricing import quote_code

    in_progress = db.scalar(select(func.count(Project.id)).where(Project.status == "in_progress"))
    completed = db.scalar(select(func.count(Project.id)).where(Project.status == "completed"))
    total_projects = db.scalar(select(func.count(Project.id)))
    rigs_available = db.scalar(select(func.count(Rig.id)).where(Rig.status == "available"))
    rigs_maintenance = db.scalar(select(func.count(Rig.id)).where(Rig.status == "maintenance"))
    rigs_assigned = db.scalar(select(func.count(Rig.id)).where(Rig.status == "assigned"))
    logs_today = db.scalar(select(func.count(DailyLog.id)).where(DailyLog.log_date == date.today()))

    quotes = db.scalars(select(Quote)).all()
    quotes_value = sum((Decimal(str((q.totals_json or {}).get("grand_total", "0"))) for q in quotes), Decimal("0"))
    invoices = db.scalars(select(Invoice)).all()
    invoices_value = sum((i.executed_total for i in invoices), Decimal("0"))

    latest_projects = db.scalars(select(Project).order_by(Project.created_at.desc()).limit(6)).all()
    cards = []
    for project in latest_projects:
        latest_quote = db.scalars(
            select(Quote).where(Quote.project_id == project.id)
            .order_by(Quote.version.desc()).limit(1)
        ).first()
        client = db.get(Client, project.client_id) if project.client_id else None
        cards.append({
            "project": project,
            "client": client,
            "quote_code": quote_code(latest_quote) if latest_quote else None,
            "quote_total": (latest_quote.totals_json or {}).get("grand_total") if latest_quote else None,
            "currency": latest_quote.currency if latest_quote else None,
        })

    return templates.TemplateResponse(request, "dashboard.html", {
        "stats": {
            "in_progress": in_progress or 0,
            "completed": completed or 0,
            "total_projects": total_projects or 0,
            "rigs_available": rigs_available or 0,
            "rigs_maintenance": rigs_maintenance or 0,
            "rigs_assigned": rigs_assigned or 0,
            "logs_today": logs_today or 0,
            "quotes_value": quotes_value,
            "invoices_value": invoices_value,
            "quotes_count": len(quotes),
        },
        "cards": cards,
        "status_ar": {"new": "جديد", "in_progress": "قيد التنفيذ", "completed": "مكتمل", "on_hold": "معلّق"},
    })

@router.get("/upload", response_class=HTMLResponse)
def upload_form(request: Request, db: Session = Depends(get_db)):
    projects = db.scalars(select(Project).order_by(Project.created_at.desc())).all()
    return templates.TemplateResponse(request, "upload.html", {"projects": projects, "error": None})

@router.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile,
    project_id: str = Form(""),
    new_project_name: str = Form(""),
    run_llm: str = Form(""),
    db: Session = Depends(get_db),
):
    suffix = Path(file.filename or "").suffix.lower()
    settings = get_settings()

    # persist upload to a temp file, then run the ingestion pipeline on it
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    try:
        resolved_project_id: int | None = int(project_id) if project_id else None
        if new_project_name.strip():
            project = Project(name=new_project_name.strip(), status="new")
            db.add(project)
            db.flush()
            resolved_project_id = project.id
        try:
            _, summary = ingest_file(db, tmp_path, project_id=resolved_project_id,
                                     run_llm=(run_llm == "1"), storage_dir=settings.upload_dir,
                                     original_name=file.filename or tmp_path.name)
        except ValueError as exc:
            projects = db.scalars(select(Project).order_by(Project.created_at.desc())).all()
            return templates.TemplateResponse(
                request, "upload.html", {"projects": projects, "error": str(exc)}, status_code=400
            )
    finally:
        tmp_path.unlink(missing_ok=True)

    doc_id = summary["document_id"]
    llm_error = (summary.get("llm") or {}).get("error") if "llm" in summary else None
    url = f"/documents/{doc_id}/review"
    if llm_error:
        url += f"?llm_error={quote(llm_error[:200])}"
    return RedirectResponse(url, status_code=303)

@router.get("/documents", response_class=HTMLResponse)
def documents_list(request: Request, db: Session = Depends(get_db)):
    docs = db.scalars(select(Document).order_by(Document.uploaded_at.desc())).all()
    rows = []
    for doc in docs:
        rows.append({"doc": doc, "counts": _counts(db, doc.id)})
    return templates.TemplateResponse(request, "documents.html", {"rows": rows})

@router.get("/documents/{document_id}/review", response_class=HTMLResponse)
def review_page(document_id: int, request: Request, llm_error: str | None = None,
                quote_error: str | None = None,
                db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if document is None:
        return HTMLResponse("document not found", status_code=404)
    items = db.scalars(
        select(BoqItem).where(BoqItem.document_id == document_id).order_by(BoqItem.id)
    ).all()
    suggestions = _active_price_items(db)
    unit_map = _price_units_map(suggestions)
    mismatches = {item.id: _suggestion_mismatch(item, unit_map) for item in items}

    from app.models import Quote
    last_quote = db.scalars(
        select(Quote).where(Quote.boq_source_document_id == document_id)
        .order_by(Quote.version.desc()).limit(1)
    ).first()
    last_quote_summary = None
    if last_quote is not None:
        last_quote_summary = {
            "id": last_quote.id,
            "code": f"GT-{last_quote.id:04d}-v{last_quote.version}",
            "grand_total": (last_quote.totals_json or {}).get("grand_total"),
            "currency": last_quote.currency,
        }

    project_name = None
    projects = db.scalars(select(Project).order_by(Project.created_at.desc())).all()
    if document.project_id:
        project = db.get(Project, document.project_id)
        project_name = project.name if project else None

    return templates.TemplateResponse(request, "review.html", {
        "document": document,
        "document_id": document_id,
        "items": items,
        "counts": _counts(db, document_id),
        "suggestions": suggestions,
        "categories": CATEGORIES,
        "status_ar": STATUS_AR,
        "mismatches": mismatches,
        "llm_error": llm_error,
        "quote_error": quote_error,
        "last_quote": last_quote_summary,
        "projects": projects,
        "project_name": project_name,
    })

@router.post("/documents/{document_id}/items/{item_id}/approve", response_class=HTMLResponse)
def approve_item(document_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    item = _get_item_or_404(db, item_id)
    item.status = BoqItemStatus.approved
    item.reviewed_by = _actor()
    item.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    _audit(db, item, "approved", {})
    db.commit()
    return _render_row(request, db, document_id, item_id)

@router.post("/documents/{document_id}/items/{item_id}/reject", response_class=HTMLResponse)
def reject_item(document_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    item = _get_item_or_404(db, item_id)
    item.status = BoqItemStatus.rejected
    item.reviewed_by = _actor()
    item.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    _audit(db, item, "rejected", {})
    db.commit()
    return _render_row(request, db, document_id, item_id)

@router.post("/documents/{document_id}/items/{item_id}/reset", response_class=HTMLResponse)
def reset_item(document_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    item = _get_item_or_404(db, item_id)
    previous = item.status.value
    item.status = BoqItemStatus.proposed
    item.reviewed_by = None
    item.reviewed_at = None
    _audit(db, item, "reset", {"from": previous})
    db.commit()
    return _render_row(request, db, document_id, item_id)

def _parse_decimal(value: str | None) -> Decimal | None:
    if value is None or not value.strip():
        return None
    try:
        return Decimal(value.strip())
    except InvalidOperation:
        return None

@router.post("/documents/{document_id}/items/{item_id}/update", response_class=HTMLResponse)
def update_item(
    document_id: int,
    item_id: int,
    request: Request,
    quantity: str = Form(""),
    unit: str = Form(""),
    unit_factor: str = Form(""),
    norm_description: str = Form(""),
    norm_category: str = Form(""),
    suggested_price_item_id: str = Form(""),
    db: Session = Depends(get_db),
):
    item = _get_item_or_404(db, item_id)
    changes: dict[str, object] = {}

    new_qty = _parse_decimal(quantity)
    if new_qty != item.quantity:
        changes["quantity"] = [str(item.quantity), str(new_qty)]
        item.quantity = new_qty

    new_unit = unit.strip() or None
    if new_unit != item.unit:
        changes["unit"] = [item.unit, new_unit]
        item.unit = new_unit

    new_factor = _parse_decimal(unit_factor) or Decimal("1")
    if new_factor != item.unit_factor:
        changes["unit_factor"] = [str(item.unit_factor), str(new_factor)]
        item.unit_factor = new_factor

    new_desc = norm_description.strip() or None
    if new_desc != item.norm_description:
        changes["norm_description"] = [item.norm_description, new_desc]
        item.norm_description = new_desc

    new_cat = norm_category.strip() or None
    if new_cat != item.norm_category:
        changes["norm_category"] = [item.norm_category, new_cat]
        item.norm_category = new_cat

    suggested = _parse_decimal(suggested_price_item_id)
    new_suggested = int(suggested) if suggested is not None else None
    if new_suggested != item.suggested_price_item_id:
        changes["suggested_price_item_id"] = [item.suggested_price_item_id, new_suggested]
        item.suggested_price_item_id = new_suggested

    if changes:
        # value edits flag the item so it goes back through the human eye
        value_fields = {"quantity", "unit", "unit_factor", "norm_description", "norm_category"}
        if value_fields & changes.keys():
            item.status = BoqItemStatus.edited
        _audit(db, item, "edited", changes)
        db.commit()
    return _render_row(request, db, document_id, item_id)

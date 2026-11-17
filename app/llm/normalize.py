"""LLM normalization pass over deterministically-extracted BOQ items.

Design rules:
- the LLM NEVER touches quantities/units (those come from deterministic code)
- human-in-the-loop is preserved: items stay status='proposed' until reviewed
- every raw LLM response is persisted on the document for audit
- failure never corrupts data: on any error, raw items remain untouched
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditLog, BoqItem, Document, PriceList, PriceListItem
from app.llm.client import LLMClient, LLMError
from app.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from app.llm.schemas import LlmParseError, parse_llm_output

MAX_CATALOG_ITEMS = 300


def _build_catalog(session: Session) -> list[dict]:
    stmt = (
        select(PriceListItem)
        .join(PriceList, PriceListItem.price_list_id == PriceList.id)
        .where(PriceList.is_active.is_(True))
        .limit(MAX_CATALOG_ITEMS)
    )
    return [
        {"code": item.code, "description": item.description, "unit": item.unit, "category": item.category}
        for item in session.scalars(stmt)
    ]


def _price_item_id_by_code(session: Session, code: str) -> int | None:
    stmt = (
        select(PriceListItem.id)
        .join(PriceList, PriceListItem.price_list_id == PriceList.id)
        .where(PriceList.is_active.is_(True), PriceListItem.code == code)
        .limit(1)
    )
    return session.scalars(stmt).first()


def normalize_document(
    session: Session,
    document_id: int,
    client: LLMClient | None = None,
) -> dict:
    """Run the LLM normalization pass. Never raises on LLM failure."""
    settings = get_settings()
    document = session.get(Document, document_id)
    if document is None:
        raise ValueError(f"document {document_id} not found")

    items = list(session.scalars(select(BoqItem).where(BoqItem.document_id == document.id)))
    if not items:
        return {"document_id": document.id, "updated": 0, "suggested": 0, "error": "no items", "skipped": []}

    lines = [
        {"line_id": item.id, "text": item.raw_description,
         "quantity": str(item.quantity) if item.quantity is not None else None,
         "unit": item.unit}
        for item in items
    ]
    catalog = _build_catalog(session)

    llm = client or LLMClient(settings.llm_base_url, settings.llm_api_key, settings.llm_model, settings.llm_timeout)
    llm_model_name = settings.llm_model if client is None else "injected"
    try:
        content, raw = llm.complete(SYSTEM_PROMPT, build_user_prompt(lines, catalog))
    except LLMError as exc:
        document.llm_model = llm_model_name
        document.llm_raw_response = {"error": str(exc), "model": llm_model_name}
        session.add(AuditLog(entity="document", entity_id=document.id,
                             action="llm_normalize_failed", diff_json={"error": str(exc)}, actor="system"))
        session.flush()
        return {"document_id": document.id, "updated": 0, "suggested": 0,
                "error": str(exc), "skipped": [item.id for item in items]}

    document.llm_model = llm_model_name
    document.llm_raw_response = {"model": llm_model_name, "response": raw, "content": content}

    try:
        parsed = parse_llm_output(content)
    except LlmParseError as exc:
        session.add(AuditLog(entity="document", entity_id=document.id,
                             action="llm_normalize_failed", diff_json={"error": exc.reason}, actor="system"))
        session.flush()
        return {"document_id": document.id, "updated": 0, "suggested": 0,
                "error": exc.reason, "skipped": [item.id for item in items]}

    by_id = {item.id: item for item in items}
    updated, suggested, skipped = 0, 0, []
    for llm_item in parsed.items:
        item = by_id.get(llm_item.line_id)
        if item is None:
            skipped.append(llm_item.line_id)  # hallucinated id — ignore safely
            continue
        item.norm_description = llm_item.norm_description
        item.norm_category = llm_item.norm_category
        if llm_item.suggested_code:
            item.suggested_price_item_id = _price_item_id_by_code(session, llm_item.suggested_code)
            if item.suggested_price_item_id is not None:
                suggested += 1
        # never widen confidence past what the deterministic parser saw
        det_conf = item.confidence if item.confidence is not None else Decimal("0.5")
        item.confidence = min(det_conf, Decimal(str(llm_item.confidence)))
        updated += 1

    missing = [item.id for item in items if item.norm_description is None]
    session.add(AuditLog(entity="document", entity_id=document.id,
                         action="llm_normalized",
                         diff_json={"updated": updated, "suggested": suggested, "missing": missing},
                         actor="system"))
    session.flush()
    return {"document_id": document.id, "updated": updated, "suggested": suggested,
            "error": None, "skipped": skipped + missing}

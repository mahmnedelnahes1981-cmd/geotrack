"""Demo helper: approve all items of document #1 and link likely price items,
then create a quote. Lets you click through the full flow instantly.

Usage: python scripts/demo_approve.py [document_id]
"""

import sys
from decimal import Decimal
from datetime import datetime, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models import BoqItem, BoqItemStatus, PriceListItem
from app.pricing import create_quote, quote_code

CODES_BY_LINE_NO = {1: "DRL.MIC.200", 2: "REINF.CAGE.150", 3: "CON.C30", 4: "SHT.DRV.18", 5: "MOB.001"}


def main() -> int:
    doc_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    session = SessionLocal()
    try:
        items = session.scalars(select(BoqItem).where(BoqItem.document_id == doc_id).order_by(BoqItem.id)).all()
        if not items:
            print(f"document {doc_id} has no items")
            return 1
        price_items = {p.code: p for p in session.scalars(select(PriceListItem))}
        for item in items:
            code = CODES_BY_LINE_NO.get(item.line_no or 0)
            if code and code in price_items:
                item.suggested_price_item_id = price_items[code].id
            item.status = BoqItemStatus.approved
            item.reviewed_by = "demo-seed"
            item.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.flush()

        from app.models import Document
        document = session.get(Document, doc_id)
        from app.models import Project
        if document.project_id is None:
            project = Project(name="مشروع تجريبي — ستائر لوحية", status="new")
            session.add(project)
            session.flush()
            document.project_id = project.id

        quote = create_quote(session, document, Decimal("14"))
        session.commit()
        print(f"approved {len(items)} items; created {quote_code(quote)} — grand total {quote.totals_json['grand_total']} {quote.currency}")
        print(f"open: http://127.0.0.1:8000/quotes/{quote.id}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

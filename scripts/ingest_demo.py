"""Demo: ingest a BOQ file end-to-end and print what the system saw.

Usage:
    python scripts/ingest_demo.py tests/fixtures/boq_en_micropiles.pdf
    python scripts/ingest_demo.py tests/fixtures/boq_en_micropiles.xlsx --llm
"""

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db import engine
from app.models import BoqItem
from app.services import ingest_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--llm", action="store_true", help="run the LLM normalization pass (needs Ollama or external API)")
    args = parser.parse_args()

    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    document, summary = ingest_file(session, args.file, run_llm=args.llm)

    print(f"document id={document.id} kind={document.kind.value} status={document.status.value} sha256={document.sha256[:12]}...")
    print(f"items extracted: {summary['items']}")
    for warning in summary["warnings"]:
        print(f"  warning: {warning}")
    if "llm" in summary:
        print(f"llm: {summary['llm']}")

    print("\nid  line qty     unit        conf  description")
    print("-" * 90)
    items = session.scalars(select(BoqItem).where(BoqItem.document_id == document.id).order_by(BoqItem.id))
    for item in items:
        print(f"{item.id:<3} {str(item.line_no or '-'):<4} {str(item.quantity or '-'):<8} "
              f"{(item.unit or '-'):<11} {str(item.confidence or '-'):<5} {item.raw_description[:48]}")
    session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

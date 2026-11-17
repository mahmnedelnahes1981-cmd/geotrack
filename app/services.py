"""Ingestion service: file on disk -> Document + proposed BoqItems."""

import hashlib
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.extract.excel import extract_file
from app.extract.pdf import extract_pdf
from app.llm.normalize import normalize_document
from app.models import BoqItem, Document, DocumentKind, DocumentStatus

_EXT_TO_KIND = {
    ".xlsx": DocumentKind.xlsx,
    ".xlsm": DocumentKind.xlsx,
    ".csv": DocumentKind.csv,
    ".pdf": DocumentKind.pdf_text,
}

_PAGE_RE = re.compile(r"page\s+(\d+)", re.I)


def kind_from_extension(ext: str) -> DocumentKind:
    try:
        return _EXT_TO_KIND[ext.lower()]
    except KeyError:
        raise ValueError(f"Unsupported file type: {ext} (expected one of {sorted(_EXT_TO_KIND)})") from None


def ingest_file(
    session: Session,
    path: str | Path,
    project_id: int | None = None,
    run_llm: bool = False,
    llm_client=None,
    storage_dir: str | Path | None = None,
    original_name: str | None = None,
) -> tuple[Document, dict]:
    settings = get_settings()
    path = Path(path)
    kind = kind_from_extension(path.suffix)

    storage = Path(storage_dir or settings.upload_dir)
    storage.mkdir(parents=True, exist_ok=True)
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    dest = storage / f"{sha256}{path.suffix.lower()}"
    shutil.copy2(path, dest)

    document = Document(
        project_id=project_id,
        kind=kind,
        original_name=original_name or path.name,
        sha256=sha256,
        storage_path=str(dest),
        status=DocumentStatus.uploaded,
    )
    session.add(document)
    session.flush()

    result = extract_pdf(path) if path.suffix.lower() == ".pdf" else extract_file(path)

    for draft in result.drafts:
        page_match = _PAGE_RE.search(draft.source_ref or "")
        session.add(BoqItem(
            document_id=document.id,
            line_no=draft.line_no,
            raw_description=draft.raw_description,
            quantity=draft.quantity,
            unit=draft.unit,
            norm_unit=draft.norm_unit,
            unit_factor=draft.unit_factor,
            confidence=draft.confidence,
            source_page=int(page_match.group(1)) if page_match else None,
            source_ref=draft.source_ref,
            raw_row=draft.raw_row,
        ))

    document.status = DocumentStatus.extracted
    document.processed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    session.flush()

    summary = {"document_id": document.id, "items": len(result.drafts),
               "warnings": list(result.warnings)}
    if run_llm:
        summary["llm"] = normalize_document(session, document.id, client=llm_client)
    session.commit()
    return document, summary

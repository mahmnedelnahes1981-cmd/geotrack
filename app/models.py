"""Base schema for the GeoTrack core engine.

Portable across SQLite (dev/tests) and PostgreSQL (prod): uses sa.JSON and
native enums. IDs are integer surrogates for now; switch to UUID if/when the
system goes multi-tenant.
"""

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class DocumentKind(str, enum.Enum):
    xlsx = "xlsx"
    csv = "csv"
    pdf_text = "pdf_text"
    pdf_scan = "pdf_scan"


class DocumentStatus(str, enum.Enum):
    uploaded = "uploaded"
    processing = "processing"
    extracted = "extracted"
    failed = "failed"


class BoqItemStatus(str, enum.Enum):
    proposed = "proposed"   # out of the extractor, awaiting human review
    approved = "approved"   # accepted by the reviewer
    rejected = "rejected"   # discarded by the reviewer
    edited = "edited"       # accepted after reviewer edits


class QuoteStatus(str, enum.Enum):
    draft = "draft"
    issued = "issued"
    accepted = "accepted"
    rejected = "rejected"


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    projects: Mapped[list["Project"]] = relationship(back_populates="client")


class Rig(Base):
    __tablename__ = "rigs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)   # e.g. DRL-001
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(48), default="micropile_drill", nullable=False)
    # micropile_drill / sheet_pile_driver / crane / excavator / other
    status: Mapped[str] = mapped_column(String(32), default="available", nullable=False)
    # available / assigned / maintenance
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"))
    rig_id: Mapped[int | None] = mapped_column(ForeignKey("rigs.id"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="new", nullable=False)
    # new / in_progress / completed / on_hold
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    client: Mapped[Client | None] = relationship(back_populates="projects")
    documents: Mapped[list["Document"]] = relationship(back_populates="project")
    quotes: Mapped[list["Quote"]] = relationship(back_populates="project")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"))
    kind: Mapped[DocumentKind] = mapped_column(Enum(DocumentKind, name="document_kind"), nullable=False)
    original_name: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"), default=DocumentStatus.uploaded, nullable=False
    )
    llm_model: Mapped[str | None] = mapped_column(String(128))
    llm_raw_response: Mapped[dict | None] = mapped_column(JSON)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)

    project: Mapped[Project | None] = relationship(back_populates="documents")
    boq_items: Mapped[list["BoqItem"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class BoqItem(Base):
    __tablename__ = "boq_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no: Mapped[int | None] = mapped_column(Integer)

    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    norm_description: Mapped[str | None] = mapped_column(Text)
    norm_category: Mapped[str | None] = mapped_column(String(120))

    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    unit: Mapped[str | None] = mapped_column(String(32))          # unit as it appears in the source
    norm_unit: Mapped[str | None] = mapped_column(String(32))     # base unit after normalization
    unit_factor: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("1"), nullable=False)

    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_ref: Mapped[str | None] = mapped_column(String(120))   # e.g. "Sheet1!R12"
    raw_row: Mapped[dict | None] = mapped_column(JSON)

    status: Mapped[BoqItemStatus] = mapped_column(
        Enum(BoqItemStatus, name="boq_item_status"), default=BoqItemStatus.proposed, nullable=False
    )

    # LLM/matcher suggestion; reviewer confirms or overrides in the Review UI
    suggested_price_item_id: Mapped[int | None] = mapped_column(ForeignKey("price_list_items.id"))

    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    document: Mapped[Document] = relationship(back_populates="boq_items")
    suggested_price_item: Mapped["PriceListItem | None"] = relationship()


class PriceList(Base):
    __tablename__ = "price_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    items: Mapped[list["PriceListItem"]] = relationship(back_populates="price_list", cascade="all, delete-orphan")

    __table_args__ = (Index("uq_price_lists_name_version", "name", "version", unique=True),)


class PriceListItem(Base):
    __tablename__ = "price_list_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    price_list_id: Mapped[int] = mapped_column(ForeignKey("price_lists.id", ondelete="CASCADE"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(120))
    unit: Mapped[str | None] = mapped_column(String(32))

    material_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    labor_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    equipment_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    overhead_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"), nullable=False)
    profit_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"), nullable=False)

    price_list: Mapped[PriceList] = relationship(back_populates="items")


class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    boq_source_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    price_list_id: Mapped[int | None] = mapped_column(ForeignKey("price_lists.id"))

    status: Mapped[QuoteStatus] = mapped_column(
        Enum(QuoteStatus, name="quote_status"), default=QuoteStatus.draft, nullable=False
    )
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"), nullable=False)
    totals_json: Mapped[dict | None] = mapped_column(JSON)
    pdf_path: Mapped[str | None] = mapped_column(String(1024))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    project: Mapped[Project] = relationship(back_populates="quotes")
    lines: Mapped[list["QuoteLine"]] = relationship(back_populates="quote", cascade="all, delete-orphan")


class QuoteLine(Base):
    __tablename__ = "quote_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False, index=True)
    boq_item_id: Mapped[int | None] = mapped_column(ForeignKey("boq_items.id"))
    price_item_id: Mapped[int | None] = mapped_column(ForeignKey("price_list_items.id"))

    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    quote: Mapped[Quote] = relationship(back_populates="lines")


class DailyLog(Base):
    __tablename__ = "daily_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    rig_id: Mapped[int | None] = mapped_column(ForeignKey("rigs.id"))

    log_date: Mapped[date] = mapped_column(Date, nullable=False)
    pile_id: Mapped[str | None] = mapped_column(String(64))          # رقم الخازوق

    depth_m: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"), nullable=False)
    concrete_m3: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"), nullable=False)
    sheet_pile_m2: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"), nullable=False)
    operating_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"), nullable=False)

    soil_notes: Mapped[str | None] = mapped_column(Text)
    breakdown_notes: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[str | None] = mapped_column(String(120))

    client_uuid: Mapped[str | None] = mapped_column(String(64), unique=True)  # offline dedupe key
    created_offline: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    project: Mapped[Project] = relationship()
    rig: Mapped[Rig | None] = relationship()

    __table_args__ = (Index("ix_daily_logs_project_date", "project_id", "log_date"),)


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("quotes.id"))
    invoice_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)

    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"), nullable=False)

    contract_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    executed_subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    executed_tax: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    executed_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)

    totals_json: Mapped[dict | None] = mapped_column(JSON)   # immutable snapshot: lines + exclusions
    pdf_path: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    project: Mapped[Project] = relationship()
    quote: Mapped[Quote | None] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    diff_json: Mapped[dict | None] = mapped_column(JSON)
    actor: Mapped[str | None] = mapped_column(String(120))
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

"""Shared extractor data structures."""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class BoqItemDraft:
    """One BOQ line as produced by an extractor, before human review."""

    line_no: int | None
    raw_description: str
    quantity: Decimal | None
    unit: str | None            # unit exactly as it appears in the source
    norm_unit: str | None       # base unit after normalization (e.g. m2, kg)
    unit_factor: Decimal        # source unit -> base unit factor (ton -> kg = 1000)
    confidence: Decimal         # 0..1, consumed by the Review UI for triage
    source_ref: str | None      # e.g. "Sheet1!R12" or page number
    raw_row: dict = field(default_factory=dict)


@dataclass
class ExtractionResult:
    drafts: list[BoqItemDraft]
    warnings: list[str] = field(default_factory=list)
    header_row: int | None = None          # 0-based index of detected header row
    mapping: dict[str, int] = field(default_factory=dict)  # field -> column index
    sheets: list[str] = field(default_factory=list)

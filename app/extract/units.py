"""Unit normalization for BOQ quantities.

Each alias maps to (dimension, factor_to_base, base_unit). The factor converts a
quantity expressed in the source unit into the base unit of its dimension.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class UnitInfo:
    dimension: str | None   # length / area / volume / mass / count / fixed / time / capacity
    factor: Decimal         # multiply source-unit quantity by this to get base unit
    base_unit: str
    known: bool


_BASE = {
    "length": "m",
    "area": "m2",
    "volume": "m3",
    "mass": "kg",
    "count": "piece",
    "fixed": "ls",
    "time": "day",
    "capacity": "l",
}

_ALIASES: dict[str, tuple[str, Decimal]] = {
    # length
    "m": ("length", Decimal("1")), "meter": ("length", Decimal("1")), "metre": ("length", Decimal("1")),
    "m.l": ("length", Decimal("1")), "ml": ("length", Decimal("1")), "mtr": ("length", Decimal("1")),
    "متر": ("length", Decimal("1")), "م": ("length", Decimal("1")), "متر طولي": ("length", Decimal("1")),
    "km": ("length", Decimal("1000")), "كم": ("length", Decimal("1000")),
    "cm": ("length", Decimal("0.01")), "سم": ("length", Decimal("0.01")),
    "mm": ("length", Decimal("0.001")), "مم": ("length", Decimal("0.001")),
    # area
    "m2": ("area", Decimal("1")), "m²": ("area", Decimal("1")), "sqm": ("area", Decimal("1")),
    "sq m": ("area", Decimal("1")), "m2.": ("area", Decimal("1")),
    "م2": ("area", Decimal("1")), "م²": ("area", Decimal("1")), "متر مربع": ("area", Decimal("1")), "مترمربع": ("area", Decimal("1")),
    # volume
    "m3": ("volume", Decimal("1")), "m³": ("volume", Decimal("1")), "cum": ("volume", Decimal("1")),
    "cu.m": ("volume", Decimal("1")), "cbm": ("volume", Decimal("1")),
    "م3": ("volume", Decimal("1")), "م³": ("volume", Decimal("1")),
    "متر مكعب": ("volume", Decimal("1")), "مترمكعب": ("volume", Decimal("1")), "متر مكعّب": ("volume", Decimal("1")),
    # mass
    "kg": ("mass", Decimal("1")), "kgs": ("mass", Decimal("1")), "kg.": ("mass", Decimal("1")),
    "كجم": ("mass", Decimal("1")), "كيلو": ("mass", Decimal("1")), "kilogram": ("mass", Decimal("1")),
    "t": ("mass", Decimal("1000")), "ton": ("mass", Decimal("1000")), "tonne": ("mass", Decimal("1000")),
    "طن": ("mass", Decimal("1000")), "طنه": ("mass", Decimal("1000")),
    # count
    "piece": ("count", Decimal("1")), "pc": ("count", Decimal("1")), "pcs": ("count", Decimal("1")),
    "no": ("count", Decimal("1")), "no.": ("count", Decimal("1")), "nos": ("count", Decimal("1")),
    "unit": ("count", Decimal("1")), "عدد": ("count", Decimal("1")), "قطعة": ("count", Decimal("1")),
    "حبة": ("count", Decimal("1")), "unit(s)": ("count", Decimal("1")),
    # fixed price
    "ls": ("fixed", Decimal("1")), "lump sum": ("fixed", Decimal("1")), "l.s.": ("fixed", Decimal("1")),
    "مقطوعية": ("fixed", Decimal("1")), "مبلغ مقطوع": ("fixed", Decimal("1")),
    # time
    "day": ("time", Decimal("1")), "days": ("time", Decimal("1")), "d": ("time", Decimal("1")),
    "يوم": ("time", Decimal("1")), "ايام": ("time", Decimal("1")), "أيام": ("time", Decimal("1")),
    "hour": ("time", Decimal("0.125")), "hr": ("time", Decimal("0.125")), "h": ("time", Decimal("0.125")),
    "ساعة": ("time", Decimal("0.125")), "ساعه": ("time", Decimal("0.125")),
    # capacity (liquids)
    "l": ("capacity", Decimal("1")), "ltr": ("capacity", Decimal("1")), "litre": ("capacity", Decimal("1")),
    "لتر": ("capacity", Decimal("1")),
}

_ARABIC_DIACRITICS = "ًٌٍَُِّْٰ"
_TATWEEL = "ـ"
_ARABIC_INDIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_EASTERN_INDIC_DIGITS = "۰۱۲۳۴۵۶۷۸۹"


def normalize_text(value: object) -> str:
    """Lowercase, trim, drop Arabic diacritics/tatweel, unify spaces."""
    if value is None:
        return ""
    text = str(value).strip().lower()
    for ch in _ARABIC_DIACRITICS + _TATWEEL:
        text = text.replace(ch, "")
    return " ".join(text.split())


def normalize_digits(text: str) -> str:
    """Convert Arabic-Indic and Eastern Arabic digits to ASCII digits."""
    out = []
    for ch in text:
        if ch in _ARABIC_INDIC_DIGITS:
            out.append(str(_ARABIC_INDIC_DIGITS.index(ch)))
        elif ch in _EASTERN_INDIC_DIGITS:
            out.append(str(_EASTERN_INDIC_DIGITS.index(ch)))
        else:
            out.append(ch)
    return "".join(out)


def normalize_unit(unit: str | None) -> UnitInfo:
    if not unit:
        return UnitInfo(dimension=None, factor=Decimal("1"), base_unit="", known=False)
    key = normalize_digits(normalize_text(unit))
    compact = key.replace(" ", "")
    for candidate in (key, compact):
        hit = _ALIASES.get(candidate)
        if hit:
            dimension, factor = hit
            return UnitInfo(dimension=dimension, factor=factor, base_unit=_BASE[dimension], known=True)
    return UnitInfo(dimension=None, factor=Decimal("1"), base_unit=key, known=False)

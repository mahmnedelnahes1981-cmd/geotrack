"""Seed data: default price list for drilling & deep-foundation work.

Prices are indicative USD figures meant as a starting point — the customer's
real price list replaces/extends this later.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PriceList, PriceListItem

# (code, category, description [EN — AR], unit, material, labor, equipment, overhead_pct, profit_pct)
DEFAULT_ITEMS: list[tuple] = [
    ("MOB.001", "mobilization", "Mobilization & demobilization of rigs and plant — تحريك المعدات وفكها", "ls",
     "2000", "500", "800", "10", "12"),
    ("DRL.MIC.200", "drilling", "Drilling micropiles Ø200mm — حفر خوازيق دقيقة قطر ٢٠٠ مم", "m",
     "8", "35", "40", "10", "15"),
    ("DRL.MIC.300", "drilling", "Drilling micropiles Ø300mm — حفر خوازيق دقيقة قطر ٣٠٠ مم", "m",
     "12", "45", "50", "10", "15"),
    ("DRL.CASE.200", "drilling", "Temporary casing Ø200mm, supply and recover — كيس مؤقت", "m",
     "15", "10", "10", "10", "12"),
    ("DRL.GROUT", "drilling", "High-strength cement grout injection — حقن جروت أسمنتي", "m3",
     "120", "60", "15", "10", "15"),
    ("DRL.JET.600", "jet_grout", "Jet grout columns Ø600mm — أعمدة جيت جروت قطر ٦٠٠ مم", "m3",
     "85", "40", "60", "10", "15"),
    ("REINF.CAGE.150", "reinforcement", "Micropile reinforcement cage Ø150mm — قفص تسليح الخوازيق", "kg",
     "1.4", "0.6", "0.2", "10", "15"),
    ("REINF.B500B", "reinforcement", "B500B steel bars, supply & fix — توريد وتركيب حديد B500B", "ton",
     "750", "120", "10", "10", "15"),
    ("SHT.SUP.AZ18", "sheet_pile", "AZ 18 sheet pile panels, supply — توريد لوحية AZ 18", "ton",
     "900", "0", "0", "8", "10"),
    ("SHT.DRV.18", "sheet_pile", "Sheet pile driving AZ 18 — دق ستائر لوحية AZ 18", "m2",
     "0", "45", "55", "10", "15"),
    ("SHT.EXT", "sheet_pile", "Sheet pile extraction — استخراج الستائر اللوحية", "m2",
     "0", "35", "45", "10", "12"),
    ("EXC.GEN", "excavation", "General excavation by mechanical means — حفر عام ميكانيكي", "m3",
     "0", "8", "12", "10", "12"),
    ("EXC.STRUT", "excavation", "Strutting & support of excavation — تدعيم جوانب الحفر", "m2",
     "35", "25", "10", "10", "15"),
    ("CON.C30", "concrete", "In-situ concrete C30/37 — صب خرسانة in-situ درجة C30/37", "m3",
     "95", "25", "5", "10", "15"),
    ("CON.C25", "concrete", "In-situ concrete C25/30 — صب خرسانة درجة C25/30", "m3",
     "85", "22", "5", "10", "15"),
    ("CON.BLIND", "concrete", "Lean concrete blinding 100mm — فرشة خرسانة نظافة ١٠ سم", "m3",
     "70", "15", "5", "10", "12"),
    ("TST.LT", "testing", "Static load test on micropile — اختبار تحميل ساكن للخوازيق", "piece",
     "1500", "300", "500", "10", "15"),
    ("TST.SONIC", "testing", "Sonic integrity testing — اختبار سلامة بالصوت", "piece",
     "250", "100", "150", "10", "12"),
    ("SURV.SET", "other", "Survey & setting out — أعمال مسح وتحديد", "day",
     "0", "350", "50", "10", "12"),
    ("DOC.ASBUILT", "other", "As-built drawings & documentation — الرسومات والملفات النهائية", "ls",
     "0", "800", "0", "10", "10"),
]


def seed_price_list(
    session: Session,
    name: str = "Drilling & Foundations Standard",
    version: str = "2026.1",
    currency: str = "USD",
    replace: bool = False,
) -> tuple[PriceList, int]:
    """Idempotent-ish: refuses to overwrite an existing list unless replace=True."""
    existing = session.scalars(
        select(PriceList).where(PriceList.name == name, PriceList.version == version)
    ).first()
    if existing is not None:
        if not replace:
            raise ValueError(f"Price list {name!r} v{version} already exists (use replace=True / --replace)")
        session.delete(existing)
        session.flush()

    price_list = PriceList(name=name, version=version, currency=currency,
                           valid_from=date.today(), is_active=True)
    session.add(price_list)
    session.flush()

    for code, category, description, unit, mat, lab, eq, oh, profit in DEFAULT_ITEMS:
        session.add(PriceListItem(
            price_list_id=price_list.id,
            code=code,
            description=description,
            category=category,
            unit=unit,
            material_cost=Decimal(mat),
            labor_cost=Decimal(lab),
            equipment_cost=Decimal(eq),
            overhead_pct=Decimal(oh),
            profit_pct=Decimal(profit),
        ))
    session.flush()
    return price_list, len(DEFAULT_ITEMS)

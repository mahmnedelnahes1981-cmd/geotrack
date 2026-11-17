"""Seed a few demo rigs (idempotent by code).

Usage: python scripts/seed_rigs.py
"""

import sys

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Rig

DEMO_RIGS = [
    ("DRL-001", "Bauer BG 24 — micropile drill", "micropile_drill", "available"),
    ("DRL-002", "Casagrande C7 XP — micropile drill", "micropile_drill", "available"),
    ("SHE-001", "Sheet pile driver ABI 12/56", "sheet_pile_driver", "available"),
    ("CRN-001", "Crawler crane 50t", "crane", "available"),
    ("EXC-001", "CAT 320 excavator", "excavator", "maintenance"),
]


def main() -> int:
    session = SessionLocal()
    created = 0
    for code, name, kind, status in DEMO_RIGS:
        existing = session.scalars(select(Rig).where(Rig.code == code)).first()
        if existing:
            continue
        session.add(Rig(code=code, name=name, kind=kind, status=status))
        created += 1
    session.commit()
    session.close()
    print(f"seeded {created} new rigs ({len(DEMO_RIGS)} total defined)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

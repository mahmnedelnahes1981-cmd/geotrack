"""Demo: assign DRL-001 to project 1 and insert two sample field logs,
so the progress screen shows real numbers immediately.

Usage: python scripts/demo_logs.py [project_id]
"""

import sys
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db import SessionLocal
from app.models import DailyLog, Project, Rig


def main() -> int:
    project_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    session = SessionLocal()
    project = session.get(Project, project_id)
    if project is None:
        print(f"project {project_id} not found")
        return 1

    rig = session.scalars(select(Rig).where(Rig.code == "DRL-001")).first()
    if rig:
        if project.rig_id and project.rig_id != rig.id:
            old = session.get(Rig, project.rig_id)
            if old:
                old.status = "available"
        project.rig_id = rig.id
        rig.status = "assigned"

    today = date.today()
    for offset, pile, depth, concrete, sheet, hours in (
        (2, "P-01", "9.5", "3.4", "120", "8.5"),
        (1, "P-02", "8.75", "3.1", "95", "7.5"),
        (0, "P-03", "9.125", "3.6", "120", "9.0"),
    ):
        session.add(DailyLog(
            project_id=project.id,
            rig_id=rig.id if rig else None,
            log_date=today - timedelta(days=offset),
            pile_id=pile,
            depth_m=Decimal(depth),
            concrete_m3=Decimal(concrete),
            sheet_pile_m2=Decimal(sheet),
            operating_hours=Decimal(hours),
            soil_notes="تربة رملية كثيفة — لا مشاكل" if offset != 0 else "طبقة طينية كثيفة عند 4م",
            recorded_by="demo-seed",
            created_offline=False,
        ))
    session.commit()
    total_depth = sum(Decimal(d[2]) for d in ((2, "P-01", "9.5"), (1, "P-02", "8.75"), (0, "P-03", "9.125")))
    print(f"assigned DRL-001, inserted 3 logs (total depth {total_depth} m)")
    session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

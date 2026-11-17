"""Seed a default drilling & deep-foundation price list into the dev database.

Usage:
    python scripts/seed_price_list.py                  # seed (fails if already seeded)
    python scripts/seed_price_list.py --replace         # wipe & re-seed
    python scripts/seed_price_list.py --currency EGP    # same list, different currency
"""

import argparse
import sys

from app.db import SessionLocal
from app.seed import seed_price_list


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replace", action="store_true", help="wipe the existing list with the same name/version first")
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--version", default="2026.1")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        price_list, count = seed_price_list(session, currency=args.currency, version=args.version, replace=args.replace)
        session.commit()
    except ValueError as exc:
        print(f"error: {exc}")
        return 1
    finally:
        session.close()

    print(f"seeded {count} price items into '{price_list.name}' v{price_list.version} ({price_list.currency})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

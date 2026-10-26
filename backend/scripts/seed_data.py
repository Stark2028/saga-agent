import argparse
import asyncio
import json
from pathlib import Path

from app.config import Settings
from app.db.models import Stock
from app.db.session import Database

SEED_DIR = Path(__file__).resolve().parents[1] / "app" / "db" / "seed"


def generate():
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    categories = ["laptop", "monitor", "keyboard", "dock", "headset"]
    catalogue = [
        dict(
            sku=f"APL-{i:03}",
            name=f"Aplus {categories[(i - 1) % 5]} {i}",
            category=categories[(i - 1) % 5],
            unit_price=100000 + i * 25000,
            available_qty=1000,
            reserved_qty=0,
            fulfilled_qty=0,
            specs={"interface": "USB-C", "currency": "INR"},
        )
        for i in range(1, 31)
    ]
    scenarios = [
        dict(
            scenario_id=f"rfq_{i:02}",
            customer_name=f"Business {i}",
            customer_email=f"buyer{i}@example.test",
            raw_request=f"{2 + i % 9} x APL-{i:03}",
            revised_raw_request=f"{6 + i % 9} x APL-{i:03}",
        )
        for i in range(1, 21)
    ]
    (SEED_DIR / "catalogue.json").write_text(
        json.dumps(catalogue, indent=2) + "\n", encoding="utf-8"
    )
    (SEED_DIR / "rfq_scenarios.json").write_text(
        json.dumps(scenarios, indent=2) + "\n", encoding="utf-8"
    )
    return catalogue, scenarios


def catalogue():
    return json.loads((SEED_DIR / "catalogue.json").read_text(encoding="utf-8"))


def scenarios():
    return json.loads((SEED_DIR / "rfq_scenarios.json").read_text(encoding="utf-8"))


async def seed(db, namespace="live"):
    async with db.transaction() as session:
        for item in catalogue():
            if not await session.get(Stock, (namespace, item["sku"])):
                session.add(Stock(namespace=namespace, **item))


async def main(seed_db):
    generate()
    if seed_db:
        db = Database(Settings().database_url)
        try:
            await db.init()
            await seed(db)
        finally:
            await db.close()
    print(
        "Generated 30 catalogue items and 20 RFQ scenarios"
        + ("; seeded live namespace" if seed_db else "")
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-db", action="store_true")
    asyncio.run(main(parser.parse_args().seed_db))

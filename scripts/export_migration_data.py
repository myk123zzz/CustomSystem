"""Export portable PostgreSQL business data without credentials."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from db.connection import get_session
from db.models import CustomerProfile, Faq, Order, Product


def serialize(row) -> dict:
    payload = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        payload[column.name] = (
            value.isoformat() if isinstance(value, (date, datetime)) else value
        )
    return payload


async def main() -> None:
    output_dir = ROOT / "migration" / "database"
    output_dir.mkdir(parents=True, exist_ok=True)
    models = (Product, Order, Faq, CustomerProfile)
    manifest = {"format": 1, "tables": {}}

    async with get_session() as session:
        for model in models:
            rows = (await session.execute(select(model))).scalars().all()
            payload = [serialize(row) for row in rows]
            filename = f"{model.__tablename__}.json"
            (output_dir / filename).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            manifest["tables"][model.__tablename__] = {
                "file": filename,
                "rows": len(payload),
            }

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

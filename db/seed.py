"""
数据导入脚本
==============
把 data/ 下的 JSON 文件导入 PostgreSQL。
每次启动时检查：如果表是空的就导入，已有数据就跳过（幂等）。
"""

import json
from pathlib import Path

from sqlalchemy import select, func

from db.connection import get_session
from db.models import Faq, Order, Product

DATA_DIR = Path(__file__).parent.parent / "data"


async def seed_all():
    """导入所有数据（幂等——已有数据则跳过）"""
    await _seed_faq()
    await _seed_products()
    await _seed_orders()
    print("  [OK] Seed data imported (FAQ, Products, Orders)")


async def _seed_faq():
    async with get_session() as session:
        # 检查是否已有数据
        count = (await session.execute(select(func.count()).select_from(Faq))).scalar()
        if count > 0:
            return  # 已导入过，跳过

        path = DATA_DIR / "faq.json"
        if not path.exists():
            return

        items = json.loads(path.read_text(encoding="utf-8"))
        for item in items:
            session.add(Faq(
                question=item["question"],
                answer=item["answer"],
                category=item.get("category", ""),
            ))
        await session.commit()


async def _seed_products():
    async with get_session() as session:
        count = (await session.execute(select(func.count()).select_from(Product))).scalar()
        if count > 0:
            return

        path = DATA_DIR / "products.json"
        if not path.exists():
            return

        items = json.loads(path.read_text(encoding="utf-8"))
        for item in items:
            session.add(Product(
                id=item["id"],
                name=item["name"],
                price=item["price"],
                stock=item["stock"],
                category=item.get("category", ""),
                description=item.get("desc", ""),
            ))
        await session.commit()


async def _seed_orders():
    async with get_session() as session:
        count = (await session.execute(select(func.count()).select_from(Order))).scalar()
        if count > 0:
            return

        path = DATA_DIR / "orders.json"
        if not path.exists():
            return

        items = json.loads(path.read_text(encoding="utf-8"))
        for item in items:
            session.add(Order(
                id=item["order_id"],
                phone=item["phone"],
                product_name=item["product"],
                price=item["price"],
                quantity=item.get("quantity", 1),
                order_date=item["date"],
                status=item["status"],
                logistics=item.get("logistics", ""),
            ))
        await session.commit()

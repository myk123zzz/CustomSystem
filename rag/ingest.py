"""
数据导入脚本：把 PostgreSQL 中的 FAQ 和商品数据导入向量知识库（Qdrant + BGE）。
每次启动时从 PostgreSQL 重新加载并重建向量（数据量小，秒级完成）。
"""

from db.connection import get_session
from db.models import Faq, Product
from rag.kb_store import KnowledgeBase
from sqlalchemy import select


async def ingest_all(kb: KnowledgeBase):
    """从 PostgreSQL 加载 FAQ + 商品到向量知识库。

    add_* 只入内存缓冲，最后调一次 kb.build() 批量编码并写入 Qdrant。
    """
    await _ingest_faq(kb)
    await _ingest_products(kb)
    kb.build()  # 批量编码 + 写入 Qdrant（一次性，远快于逐条编码）
    print(f"  [RAG] 知识库加载完成")


async def _ingest_faq(kb: KnowledgeBase):
    async with get_session() as session:
        result = await session.execute(select(Faq))
        faqs = result.scalars().all()

        if not faqs:
            print("  [RAG] FAQ 表为空，跳过")
            return

        for faq in faqs:
            kb.add_faq(
                faq_id=str(faq.id),
                question=faq.question,
                answer=faq.answer,
                category=faq.category or "",
            )
        print(f"  [RAG] FAQ 加载: {len(faqs)} 条")


async def _ingest_products(kb: KnowledgeBase):
    async with get_session() as session:
        result = await session.execute(select(Product))
        products = result.scalars().all()

        if not products:
            print("  [RAG] 商品表为空，跳过")
            return

        for p in products:
            kb.add_product(
                product_id=p.id,
                name=p.name,
                description=p.description or "",
                category=p.category or "",
            )
        print(f"  [RAG] 商品加载: {len(products)} 条")

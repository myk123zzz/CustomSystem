"""
FAQ 查询工具
==============
Agent 调用此工具搜索 FAQ 知识库。

查询策略（两级降级）：
  1. PostgreSQL ILIKE 精确/模糊匹配（快）
  2. 降级到 RAG 向量语义搜索（慢但能理解同义词）

Agent 不知道有数据库还是向量库——它只知道调这个工具能拿到答案。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from db.connection import get_session
from db.models import Faq
from tools.base import Tool

if TYPE_CHECKING:
    from rag.kb_store import KnowledgeBase


class FaqLookupTool(Tool):
    """搜索 FAQ 知识库。SQL ILIKE 优先，不命中时自动降级到 RAG 向量搜索。"""

    def __init__(self, kb: "KnowledgeBase | None" = None):
        """
        Args:
            kb: 向量知识库引用（可选）。传入后，SQL 搜索无结果时自动
               降级到 RAG 语义搜索，不再返回"未找到"废话。
        """
        self._kb = kb

    @property
    def name(self) -> str:
        return "faq_lookup"

    @property
    def description(self) -> str:
        return (
            "搜索 FAQ 常见问题知识库。当用户咨询退换货政策、发货时间、保修、发票、"
            "支付方式、快递等问题时，优先调用此工具。\n"
            "参数 query: 搜索关键词，如 '退货'、'发货'、'保修'。\n"
            "返回匹配的 FAQ 条目（含问题和标准答案）。"
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词。用简短的关键词而不是整句话，如 '退货'、'发货时间'、'保修'",
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str) -> str:
        # ── 第一级：SQL ILIKE ──
        async with get_session() as session:
            print(f"     [faq_lookup] SQL 搜索: '{query}' ...")
            stmt = (
                select(Faq)
                .where(Faq.question.ilike(f"%{query}%"))
                .limit(3)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            print(f"     [faq_lookup] 问题匹配到 {len(rows)} 条结果")
            if not rows:
                print(f"     [faq_lookup] 问题未匹配，尝试分类搜索...")
                stmt2 = (
                    select(Faq)
                    .where(Faq.category.ilike(f"%{query}%"))
                    .limit(3)
                )
                result2 = await session.execute(stmt2)
                rows = result2.scalars().all()
                print(f"     [faq_lookup] 分类搜索匹配到 {len(rows)} 条结果")

            if rows:
                lines = ["找到以下 FAQ 匹配结果：\n"]
                for faq in rows:
                    lines.append(f"【{faq.category or '通用'}】Q: {faq.question}")
                    lines.append(f"A: {faq.answer}")
                    lines.append("")
                return "\n".join(lines)

        # ── 第二级：RAG 向量语义搜索 ──
        if self._kb is not None:
            print(f"     [faq_lookup] SQL 未命中 → RAG 语义降级")
            hits = self._kb.search_faq(query, n_results=3)
            if hits:
                top = hits[0]
                print(f"     [faq_lookup] RAG 命中: '{top.get('question')}' score={top['score']}")
                lines = ["通过语义搜索匹配到以下 FAQ：\n"]
                for h in hits[:3]:
                    lines.append(f"【{h.get('category', '通用')}】Q: {h.get('question', '')}")
                    lines.append(f"（语义相似度: {h['score']}）")
                    lines.append(f"{h['content'][:400]}")
                    lines.append("")
                return "\n".join(lines)
            print(f"     [faq_lookup] RAG 也未命中")

        return "(FAQ 知识库中没有找到相关信息，建议尝试 rag_search 工具或转人工)"


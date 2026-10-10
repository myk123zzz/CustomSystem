"""
RAG 语义搜索工具
==================
Agent 可调用此工具在知识库中做语义搜索。
和 faq_lookup 的区别：
  - faq_lookup: SQL 模糊匹配，用户说"退货"才能匹配到"退货政策"
  - rag_search: 语义匹配，用户说"退钱"也能匹配到"退款政策"
"""

from rag.kb_store import KnowledgeBase
from tools.base import Tool


class RAGSearchTool(Tool):
    """语义搜索知识库（FAQ + 商品）。在关键词精确匹配失败后使用。"""

    def __init__(self, kb: KnowledgeBase):
        self.kb = kb

    @property
    def name(self) -> str:
        return "rag_search"

    @property
    def description(self) -> str:
        return (
            "在知识库中做语义搜索（FAQ + 商品信息）。"
            "当 faq_lookup 精确搜索没有结果、或者用户用了非标准说法时使用。"
            "例如用户说'退钱'而 faq_lookup 没找到——用 rag_search('退钱') 可以匹配到'退款政策'。\n"
            "参数 query: 用户的原始问题或重新组织的搜索词。"
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "要搜索的问题或关键词。用自然语言描述比单个关键词效果更好",
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str) -> str:
        """执行语义搜索，返回 top 3 结果。"""
        print(f"     [rag_search] 语义搜索: '{query}' ...")
        hits = self.kb.search_all(query, n_results=3)

        if not hits:
            print(f"     [rag_search] 未找到语义匹配结果")
            return "(知识库语义搜索未找到相关信息)"

        print(f"     [rag_search] 找到 {len(hits)} 条结果，最高相似度 {hits[0]['score']}")
        lines = ["语义搜索匹配到以下内容：\n"]
        for h in hits:
            lines.append(f"  [相似度: {h['score']}] {h['content'][:200]}")
        return "\n".join(lines)

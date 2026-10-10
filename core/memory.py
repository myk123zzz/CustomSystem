"""
记忆系统 —— 对话摘要 + 长期记忆（借鉴 nanobot 的 Consolidator/Dream 模式）
===========================================================================
nanobot 的记忆系统分两层：
  1. Consolidation：token 预算超限时，LLM 摘要旧消息 → 注入 system prompt
  2. Dream：后台定期跑，从 history.jsonl 更新 MEMORY.md

我们的客服场景适配：
  - 会话自然结束（问题解决 / 转人工）→ LLM 摘要整段对话
  - 摘要存入 CustomerProfile.last_summary（PostgreSQL，跨会话持久）
  - 顾客再次来访 → 摘要注入 system prompt，Agent 知道"上次聊了什么"

这跟 nanobot 的 Dream 本质一样——从原始对话中提取长期记忆——
但触发时机不同（会话结束 vs 定期扫描），更适合客服场景。
"""

from core.provider import LLMProvider


CONSOLIDATION_PROMPT = """你是一个对话摘要助手。请用 2-3 句话总结以下客服对话的核心内容。

要求：
  - 只写事实，不评价
  - 包含：顾客问题、客服做了什么、是否已解决
  - 中文输出，不超过 100 字

对话内容：
---
{conversation}
---

摘要："""


class MemoryConsolidator:
    """对话摘要器——把一段对话压缩为 2-3 句摘要。

    用法::

        mc = MemoryConsolidator(provider)
        summary = await mc.summarize(messages)
        # summary → "顾客咨询退货政策，客服已提供退货流程说明，问题已解决。"
    """

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def summarize(
        self,
        messages: list[dict[str, str]],
    ) -> str:
        """将一段对话摘要为简短文本。

        Args:
            messages: 对话消息列表（user + assistant 交替）

        Returns:
            2-3 句中文摘要，失败时返回空字符串
        """
        if not messages:
            return ""

        # 构建对话文本（截断过长内容）
        lines: list[str] = []
        total_chars = 0
        for msg in messages[-20:]:  # 最多取最近 20 条
            role = "顾客" if msg.get("role") == "user" else "客服"
            content = str(msg.get("content", ""))[:200]  # 每条截断到 200 字
            lines.append(f"{role}: {content}")
            total_chars += len(content)
            if total_chars > 3000:
                break

        conversation = "\n".join(lines)

        try:
            response = await self.provider.chat(
                messages=[{
                    "role": "user",
                    "content": CONSOLIDATION_PROMPT.format(conversation=conversation),
                }],
                tools=None,
            )
            if response.content:
                return response.content.strip()[:200]
        except Exception:
            pass

        return ""

    @staticmethod
    def fallback_summary(messages: list[dict[str, str]]) -> str:
        """不依赖 LLM 的降级摘要——取第一条用户消息作为摘要。

        当 LLM 不可用时使用。
        """
        for msg in messages:
            if msg.get("role") == "user":
                content = str(msg.get("content", ""))[:80]
                return f"顾客曾咨询: {content}"
        return ""

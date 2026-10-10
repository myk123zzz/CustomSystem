"""Deterministic request execution that never calls an LLM."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.intent_router import GREETING_REPLY, Intent
from core.router import RouteDecision, RouteTarget


@dataclass(frozen=True)
class FastPathResult:
    handled: bool
    reply: str = ""
    tools_called: list[str] = field(default_factory=list)
    fallback_target: RouteTarget | None = None
    error: str | None = None


class FastPathExecutor:
    """Execute fixed, low-risk workflows without invoking a model."""

    def __init__(self, tools, kb=None):
        self.tools = tools
        self.kb = kb

    async def execute(self, decision: RouteDecision, message: str) -> FastPathResult:
        if decision.target is not RouteTarget.FAST_PATH:
            return FastPathResult(False, error="decision_is_not_fast_path")

        handlers = {
            Intent.GREETING: self._greeting,
            Intent.FAQ: self._faq,
            Intent.PRODUCT: self._product,
            Intent.ORDER_QUERY: self._order,
            Intent.LOGISTICS: self._order,
        }
        handler = handlers.get(decision.intent)
        if handler is None:
            return FastPathResult(False, error=f"unsupported_intent:{decision.intent.value}")

        return await handler(decision, message)

    async def _greeting(self, _decision: RouteDecision, _message: str) -> FastPathResult:
        return FastPathResult(True, GREETING_REPLY)

    async def _faq(self, _decision: RouteDecision, message: str) -> FastPathResult:
        result = await self.tools.execute("faq_lookup", {"query": message})
        if self._is_tool_error(result) or "没有找到相关信息" in result:
            return FastPathResult(
                False,
                tools_called=["faq_lookup"],
                fallback_target=self._faq_fallback_target(message),
                error="faq_not_resolved",
            )
        return FastPathResult(True, result, ["faq_lookup"])

    async def _product(self, _decision: RouteDecision, message: str) -> FastPathResult:
        if self.kb is None:
            return FastPathResult(
                False,
                fallback_target=RouteTarget.PRESALES,
                error="knowledge_base_unavailable",
            )

        hits = self.kb.search_products(message, n_results=3)
        if not hits or hits[0].get("score", 0.0) <= 0.3:
            return FastPathResult(
                False,
                fallback_target=RouteTarget.PRESALES,
                error="product_not_resolved",
            )

        lines = ["为您找到以下相关商品：", ""]
        for hit in hits[:3]:
            lines.extend([
                f"**{hit.get('name', '')}**",
                str(hit.get("content", ""))[:200],
                "",
            ])
        return FastPathResult(True, "\n".join(lines).strip())

    async def _order(self, decision: RouteDecision, _message: str) -> FastPathResult:
        order_id = decision.entities.get("order_id")
        if not order_id:
            return FastPathResult(
                False,
                fallback_target=RouteTarget.IN_SALES,
                error="missing_order_id",
            )

        result = await self.tools.execute("order_query", {"order_id": order_id})
        if self._is_tool_error(result):
            return FastPathResult(
                False,
                tools_called=["order_query"],
                fallback_target=RouteTarget.HUMAN,
                error="order_service_error",
            )
        return FastPathResult(True, result, ["order_query"])

    @staticmethod
    def _is_tool_error(result: str) -> bool:
        return result.startswith(("错误:", "参数错误:", "工具执行失败:", "工具执行异常:"))

    @staticmethod
    def _faq_fallback_target(message: str) -> RouteTarget:
        if any(word in message for word in ("退", "换货", "保修", "质保", "退款")):
            return RouteTarget.AFTERSALES
        if any(word in message for word in ("物流", "发货", "地址", "订单", "支付")):
            return RouteTarget.IN_SALES
        return RouteTarget.PRESALES


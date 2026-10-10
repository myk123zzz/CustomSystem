"""Deterministic dependencies for reproducible CI evaluation."""

from __future__ import annotations

from dataclasses import dataclass

from core.context_store import ContextStore
from core.fast_path import FastPathExecutor
from core.router import RouteTarget, Router
from core.service import CustomerServiceEngine
from core.session_memory import SessionMemoryManager
from core.session_state import SessionContext
from core.trace import TraceStore


class DeterministicTools:
    async def execute(self, name, params):
        if name == "order_query":
            order_id = params.get("order_id") or "88001"
            return f"订单{order_id}状态正常。"
        return {
            "faq_lookup": "支持7天无理由退货。",
            "request_human": "已转人工客服。",
        }.get(name, "工具完成")


@dataclass
class DeterministicTurn:
    final_content: str
    tools_called: list[str]
    llm_calls: int = 2
    stop_reason: str = "completed"


class DeterministicAgents:
    async def execute(self, *, target, **kwargs):
        tool_by_target = {
            RouteTarget.PRESALES: "rag_search",
            RouteTarget.IN_SALES: "order_query",
            RouteTarget.AFTERSALES: "order_query",
        }
        message = kwargs.get("message", "")
        needs_identifier = target in {RouteTarget.IN_SALES, RouteTarget.AFTERSALES}
        has_order_id = any(
            token.isdigit() and len(token) == 5
            for token in message.replace("，", " ").replace("。", " ").split()
        ) or any(str(number) in message for number in range(88001, 89000))
        tools = [] if needs_identifier and not has_order_id else [tool_by_target[target]]
        return DeterministicTurn("专业客服已处理。", tools)


class DeterministicKnowledgeBase:
    def search_products(self, query, n_results=3):
        return [{
            "name": "Qi2 超薄磁吸充电宝 5000mAh",
            "content": "Qi2 磁吸充电宝，售价149元。",
            "score": 0.9,
        }]


def build_deterministic_engine() -> CustomerServiceEngine:
    tools = DeterministicTools()
    context_store = ContextStore()
    return CustomerServiceEngine(
        Router(session_factory=lambda key: SessionContext(context_store, key)),
        FastPathExecutor(tools, kb=DeterministicKnowledgeBase()),
        DeterministicAgents(),
        tools,
        SessionMemoryManager(context_store),
        TraceStore(),
    )

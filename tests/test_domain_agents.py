from typing import Any

import pytest

from core.domain_agents import DomainAgentExecutor
from core.router import RouteTarget
from tools.base import Tool
from tools.registry import ToolRegistry


class NamedTool(Tool):
    def __init__(self, tool_name: str):
        self._name = tool_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._name

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> str:
        return "ok"


class FakeLoop:
    def __init__(self):
        self.calls = []

    async def process_direct(self, **kwargs):
        self.calls.append(kwargs)
        return "done"


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for name in ("faq_lookup", "rag_search", "order_query", "request_human"):
        registry.register(NamedTool(name))
    return registry


def test_each_agent_has_a_distinct_tool_whitelist():
    executor = DomainAgentExecutor(FakeLoop(), build_registry())

    assert set(executor.tool_names_for(RouteTarget.PRESALES)) == {"faq_lookup", "rag_search"}
    assert set(executor.tool_names_for(RouteTarget.IN_SALES)) == {
        "faq_lookup", "order_query", "rag_search"
    }
    assert set(executor.tool_names_for(RouteTarget.AFTERSALES)) == {
        "faq_lookup", "order_query", "rag_search", "request_human"
    }


@pytest.mark.asyncio
async def test_domain_agent_reuses_loop_with_prompt_and_tool_view():
    loop = FakeLoop()
    executor = DomainAgentExecutor(loop, build_registry())

    await executor.execute(
        RouteTarget.IN_SALES,
        "订单显示签收但没收到",
        "s1",
        profile_text="VIP",
        context_text="订单88001",
    )

    call = loop.calls[0]
    assert call["content"] == "订单显示签收但没收到"
    assert "售中履约客服" in call["instructions_text"]
    assert set(call["tools_override"].tool_names) == {
        "faq_lookup", "order_query", "rag_search"
    }


@pytest.mark.asyncio
async def test_non_agent_target_is_rejected():
    executor = DomainAgentExecutor(FakeLoop(), build_registry())

    with pytest.raises(ValueError, match="不是可执行"):
        await executor.execute(RouteTarget.FAST_PATH, "你好", "s1")

from typing import Any

import pytest

from core.domain_agents import DomainAgentExecutor
from core.loop import AgentLoop
from core.provider import LLMResponse, ToolCallRequest
from core.router import RouteTarget
from core.persistence import SessionStore
from tools.base import Tool
from tools.registry import ToolRegistry


class StaticTool(Tool):
    def __init__(self, name: str, result: str):
        self._name = name
        self.result = result
        self.calls = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._name

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return self.result


class ScriptedProvider:
    def __init__(self):
        self.calls = []
        self.responses = [
            LLMResponse(
                tool_calls=[
                    ToolCallRequest("call-1", "rag_search", {"query": "轻量充电宝"})
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="推荐轻量充电宝。", finish_reason="stop"),
        ]

    async def chat_with_retry(self, messages, tools=None, model=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        return self.responses.pop(0)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_presales_react_uses_only_allowed_tools(tmp_path):
    (tmp_path / "AGENTS.md").write_text("客服基础规则", encoding="utf-8")
    provider = ScriptedProvider()
    registry = ToolRegistry()
    faq = StaticTool("faq_lookup", "FAQ")
    rag = StaticTool("rag_search", "轻量充电宝，重量180g")
    order = StaticTool("order_query", "订单")
    human = StaticTool("request_human", "人工")
    for tool in (faq, rag, order, human):
        registry.register(tool)

    session_store = SessionStore(tmp_path / "sessions")
    loop = AgentLoop(
        None, provider, str(tmp_path), tools=registry, session_store=session_store
    )
    agents = DomainAgentExecutor(loop, registry)

    result = await agents.execute(
        RouteTarget.PRESALES,
        "推荐一个轻量充电宝",
        "s1",
    )

    assert result.final_content == "推荐轻量充电宝。"
    assert result.tools_called == ["rag_search"]
    assert rag.calls == [{"query": "轻量充电宝"}]

    exposed = {
        item["function"]["name"]
        for item in provider.calls[0]["tools"]
    }
    assert exposed == {"faq_lookup", "rag_search"}
    assert any(
        msg.get("role") == "tool" and "重量180g" in msg.get("content", "")
        for msg in provider.calls[1]["messages"]
    )
    history = await session_store.load_history("s1")
    assert history[0] == {"role": "user", "content": "推荐一个轻量充电宝"}
    assert "运行时上下文" not in history[0]["content"]

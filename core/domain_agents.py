"""Definitions and execution adapter for the three domain ReAct agents."""

from __future__ import annotations

from dataclasses import dataclass

from core.router import RouteTarget


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    instructions: str
    allowed_tools: frozenset[str]


AGENT_DEFINITIONS = {
    RouteTarget.PRESALES: AgentDefinition(
        name="presales",
        instructions=(
            "## 当前角色：售前顾问\n"
            "负责复杂商品推荐、商品比较和需求澄清。先理解预算、设备和使用场景，"
            "再基于工具结果推荐；不得编造库存、价格或商品参数。"
        ),
        allowed_tools=frozenset({"faq_lookup", "rag_search"}),
    ),
    RouteTarget.IN_SALES: AgentDefinition(
        name="in_sales",
        instructions=(
            "## 当前角色：售中履约客服\n"
            "负责订单、发货、物流和履约异常。订单与物流事实必须来自工具；"
            "缺少订单号时先追问，不得推测订单状态。"
        ),
        allowed_tools=frozenset({"order_query", "faq_lookup", "rag_search"}),
    ),
    RouteTarget.AFTERSALES: AgentDefinition(
        name="aftersales",
        instructions=(
            "## 当前角色：售后客服\n"
            "负责退款、退货、换货、保修和一般投诉。先核验订单和政策，"
            "缺少信息时明确追问；当前没有自动退款写工具，不得声称退款已经完成，"
            "必要时调用人工接管。"
        ),
        allowed_tools=frozenset({
            "order_query", "faq_lookup", "rag_search", "request_human",
        }),
    ),
}


class DomainAgentExecutor:
    """Run one selected domain agent on the shared ReAct engine."""

    def __init__(self, loop, tools):
        self.loop = loop
        self.tools = tools
        self._tool_views = {
            target: tools.subset(definition.allowed_tools)
            for target, definition in AGENT_DEFINITIONS.items()
        }

    async def execute(
        self,
        target: RouteTarget,
        message: str,
        session_key: str,
        *,
        profile_text: str = "",
        context_text: str = "",
    ):
        definition = AGENT_DEFINITIONS.get(target)
        if definition is None:
            raise ValueError(f"目标不是可执行的 Domain Agent: {target.value}")

        return await self.loop.process_direct(
            content=message,
            session_key=session_key,
            profile_text=profile_text,
            context_text=context_text,
            instructions_text=definition.instructions,
            tools_override=self._tool_views[target],
        )

    def tool_names_for(self, target: RouteTarget) -> list[str]:
        try:
            return self._tool_views[target].tool_names
        except KeyError as exc:
            raise ValueError(f"目标不是 Domain Agent: {target.value}") from exc


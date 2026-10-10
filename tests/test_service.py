from dataclasses import dataclass, field

from core.context_store import ContextStore
from core.fast_path import FastPathExecutor
from core.router import RouteTarget, Router
from core.service import CustomerServiceEngine
from core.session_memory import SessionMemoryManager
from core.trace import TraceStore
from core.persistence import SessionStore


class FakeTools:
    def __init__(self):
        self.calls = []

    async def execute(self, name, params):
        self.calls.append((name, params))
        if name == "faq_lookup":
            return "支持7天无理由退货。"
        if name == "order_query":
            return "订单88001，物流运输中。"
        if name == "request_human":
            return "已转人工。"
        return "ok"


@dataclass
class FakeTurn:
    final_content: str = "Agent完成"
    tools_called: list[str] = field(default_factory=lambda: ["rag_search"])
    llm_calls: int = 2
    stop_reason: str = "completed"


class FakeAgents:
    def __init__(self):
        self.calls = []

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return FakeTurn()


def build_engine():
    tools = FakeTools()
    agents = FakeAgents()
    memory = SessionMemoryManager(ContextStore())
    traces = TraceStore()
    engine = CustomerServiceEngine(
        Router(), FastPathExecutor(tools), agents, tools, memory, traces
    )
    return engine, tools, agents, memory, traces


async def test_engine_fast_path_is_zero_llm():
    engine, tools, agents, _memory, traces = build_engine()

    result = await engine.process("订单88001到哪了", "s1")

    assert result.final_target is RouteTarget.FAST_PATH
    assert result.llm_calls == 0
    assert result.tools_called == ["order_query"]
    assert agents.calls == []
    assert traces.recent()[0]["llm_calls"] == 0


async def test_engine_runs_only_selected_agent():
    engine, _tools, agents, _memory, traces = build_engine()

    result = await engine.process("推荐一个适合出差的充电宝", "s1")

    assert result.final_target is RouteTarget.PRESALES
    assert result.llm_calls == 2
    assert len(agents.calls) == 1
    assert agents.calls[0]["target"] is RouteTarget.PRESALES
    assert traces.recent()[0]["target"] == "presales"


async def test_engine_persists_after_sales_waiting_state():
    engine, _tools, _agents, memory, _traces = build_engine()

    await engine.process("我要退款", "s1")

    state = memory.context("s1")
    assert state["domain"] == "aftersales"
    assert state["waiting_for"] == "订单号"


async def test_engine_handoff_skips_agent():
    engine, tools, agents, memory, traces = build_engine()

    result = await engine.process("我要找负责人投诉", "s1")

    assert result.final_target is RouteTarget.HUMAN
    assert result.reply == "已转人工。"
    assert agents.calls == []
    assert tools.calls[-1][0] == "request_human"
    assert memory.context("s1")["phase"] == "handoff"
    assert traces.recent()[0]["tools_called"] == ["request_human"]


async def test_engine_persists_fast_path_conversation(tmp_path):
    tools = FakeTools()
    store = SessionStore(tmp_path)
    memory = SessionMemoryManager(ContextStore(), store)
    engine = CustomerServiceEngine(
        Router(), FastPathExecutor(tools), FakeAgents(), tools, memory, TraceStore()
    )

    await engine.process("你好", "fast:history")

    history = await store.load_history("fast:history")
    assert history[0]["content"] == "你好"
    assert history[1]["role"] == "assistant"

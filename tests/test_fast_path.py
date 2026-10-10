from core.fast_path import FastPathExecutor
from core.intent_router import Intent
from core.router import RouteDecision, RouteTarget


class FakeTools:
    def __init__(self, results=None):
        self.results = results or {}
        self.calls = []

    async def execute(self, name, params):
        self.calls.append((name, params))
        return self.results.get(name, "ok")


class FakeKB:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def search_products(self, message, n_results):
        self.calls.append((message, n_results))
        return self.hits


async def test_greeting_has_no_tool_call():
    tools = FakeTools()
    executor = FastPathExecutor(tools)
    decision = RouteDecision(RouteTarget.FAST_PATH, Intent.GREETING)

    result = await executor.execute(decision, "你好")

    assert result.handled is True
    assert tools.calls == []


async def test_order_lookup_uses_fixed_tool_and_arguments():
    tools = FakeTools({"order_query": "订单88001运输中"})
    executor = FastPathExecutor(tools)
    decision = RouteDecision(
        RouteTarget.FAST_PATH,
        Intent.ORDER_QUERY,
        {"order_id": "88001"},
    )

    result = await executor.execute(decision, "查订单88001")

    assert result.handled is True
    assert result.tools_called == ["order_query"]
    assert tools.calls == [("order_query", {"order_id": "88001"})]


async def test_order_tool_failure_fails_closed_to_human():
    tools = FakeTools({"order_query": "工具执行失败: database unavailable"})
    executor = FastPathExecutor(tools)
    decision = RouteDecision(
        RouteTarget.FAST_PATH,
        Intent.LOGISTICS,
        {"order_id": "88001"},
    )

    result = await executor.execute(decision, "订单88001到哪了")

    assert result.handled is False
    assert result.fallback_target is RouteTarget.HUMAN
    assert result.error == "order_service_error"


async def test_faq_miss_falls_back_to_matching_domain():
    tools = FakeTools({"faq_lookup": "(FAQ 知识库中没有找到相关信息)"})
    executor = FastPathExecutor(tools)
    decision = RouteDecision(RouteTarget.FAST_PATH, Intent.FAQ)

    result = await executor.execute(decision, "怎么退款")

    assert result.handled is False
    assert result.fallback_target is RouteTarget.AFTERSALES


async def test_product_hit_is_rendered_without_tools():
    kb = FakeKB([{"name": "轻量充电宝", "content": "重量180g", "score": 0.8}])
    tools = FakeTools()
    executor = FastPathExecutor(tools, kb=kb)
    decision = RouteDecision(RouteTarget.FAST_PATH, Intent.PRODUCT)

    result = await executor.execute(decision, "轻量充电宝多少钱")

    assert result.handled is True
    assert "轻量充电宝" in result.reply
    assert tools.calls == []


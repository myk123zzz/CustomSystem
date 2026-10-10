from dataclasses import dataclass

import pytest

from core.context_store import ContextStore
from core.intent_router import Intent
from core.router import RouteTarget, Router
from core.session_state import SessionContext


@dataclass
class FakeResponse:
    content: str


class FakeProvider:
    def __init__(self, label: str):
        self.label = label
        self.calls = 0

    async def chat(self, messages, tools=None):
        self.calls += 1
        return FakeResponse(self.label)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "target", "intent"),
    [
        ("你好", RouteTarget.FAST_PATH, Intent.GREETING),
        ("怎么退款", RouteTarget.FAST_PATH, Intent.FAQ),
        ("订单88001", RouteTarget.FAST_PATH, Intent.ORDER_QUERY),
        ("帮我查订单", RouteTarget.IN_SALES, Intent.ORDER_QUERY),
        ("订单88002到哪了", RouteTarget.FAST_PATH, Intent.LOGISTICS),
        ("快递一直没收到", RouteTarget.IN_SALES, Intent.LOGISTICS),
        ("这个充电头多少钱", RouteTarget.FAST_PATH, Intent.PRODUCT),
        ("推荐一个适合出差的充电宝", RouteTarget.PRESALES, Intent.PRODUCT),
        ("我要退订单88001", RouteTarget.AFTERSALES, Intent.AFTER_SALES),
        ("我要找负责人投诉", RouteTarget.HUMAN, Intent.COMPLAINT),
    ],
)
async def test_router_selects_expected_target(message, target, intent):
    router = Router()

    decision = await router.route(message)

    assert decision.target is target
    assert decision.intent is intent


@pytest.mark.asyncio
async def test_unknown_request_uses_llm_fallback():
    provider = FakeProvider("in_sales")
    router = Router(provider=provider)

    decision = await router.route("这个情况比较奇怪，麻烦综合看看")

    assert decision.target is RouteTarget.IN_SALES
    assert decision.confidence == 0.75
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_invalid_llm_route_fails_closed_to_human():
    router = Router(provider=FakeProvider("unknown"))

    decision = await router.route("无法通过规则理解的请求")

    assert decision.target is RouteTarget.HUMAN
    assert decision.confidence == 0.0


@pytest.mark.asyncio
async def test_active_after_sales_session_overrides_surface_message():
    store = ContextStore()

    def session_factory(key: str) -> SessionContext:
        return SessionContext(store, key)

    session_factory("s1").agent_is_waiting("退款原因", intent="退款")
    router = Router(session_factory=session_factory)

    decision = await router.route("充不上电", session_key="s1")

    assert decision.target is RouteTarget.AFTERSALES
    assert decision.intent is Intent.AFTER_SALES
    assert decision.reason.startswith("continue_active_session")


@pytest.mark.asyncio
async def test_vague_followup_stays_in_established_after_sales_domain():
    store = ContextStore()

    def session_factory(key: str) -> SessionContext:
        return SessionContext(store, key)

    store.set("s1", "domain", "aftersales")
    store.set("s1", "intent", "after_sales")
    store.set("s1", "slots", {"order_id": "88012", "action": "退款"})
    router = Router(session_factory=session_factory)

    decision = await router.route("充不上电", session_key="s1")

    assert decision.target is RouteTarget.AFTERSALES
    assert decision.intent is Intent.AFTER_SALES
    assert decision.reason == "continue_domain:aftersales"


@pytest.mark.asyncio
async def test_stats_keep_admin_compatibility_fields():
    router = Router()

    await router.route("你好")
    await router.route("推荐一个适合出差的充电宝")

    stats = router.stats
    assert stats["total_requests"] == 2
    assert stats["agent_calls"] == 1
    assert stats["direct_pct"] == 50.0
    assert stats["agent_pct"] == 50.0
    assert stats["targets"]["fast_path"] == 1

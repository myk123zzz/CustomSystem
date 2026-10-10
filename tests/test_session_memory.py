from core.context_store import ContextStore
from core.intent_router import Intent
from core.router import RouteDecision, RouteTarget, Router
from core.session_memory import SessionMemoryManager
from core.session_state import Phase, SessionContext
from core.persistence import SessionStore


async def test_after_sales_without_order_waits_for_order_id():
    store = ContextStore()
    memory = SessionMemoryManager(store)
    decision = RouteDecision(RouteTarget.AFTERSALES, Intent.AFTER_SALES)

    state = await memory.update("s1", decision, RouteTarget.AFTERSALES, "我要退款")

    assert state["domain"] == "aftersales"
    assert state["intent"] == "after_sales"
    assert state["phase"] == Phase.COLLECTING_INFO.value
    assert state["waiting_for"] == "订单号"
    assert state["slots"]["action"] == "退款"


async def test_followup_order_id_is_extracted_and_completes_collection():
    store = ContextStore()
    memory = SessionMemoryManager(store)

    initial = RouteDecision(RouteTarget.AFTERSALES, Intent.AFTER_SALES)
    await memory.update("s1", initial, RouteTarget.AFTERSALES, "我要退款")

    def factory(key: str) -> SessionContext:
        return SessionContext(store, key)

    decision = await Router(session_factory=factory).route("88001", session_key="s1")
    state = await memory.update("s1", decision, RouteTarget.AFTERSALES, "88001")

    assert decision.target is RouteTarget.AFTERSALES
    assert decision.entities["order_id"] == "88001"
    assert state["slots"]["order_id"] == "88001"
    assert state["phase"] == Phase.NORMAL.value
    assert state["waiting_for"] == ""


async def test_handoff_sets_handoff_phase():
    store = ContextStore()
    memory = SessionMemoryManager(store)
    decision = RouteDecision(RouteTarget.HUMAN, Intent.COMPLAINT)

    state = await memory.update("s1", decision, RouteTarget.HUMAN, "我要投诉")

    assert state["domain"] == "aftersales"
    assert state["phase"] == Phase.HANDOFF.value


async def test_switching_to_presales_clears_order_task_slots():
    store = ContextStore()
    memory = SessionMemoryManager(store)
    await memory.update(
        "s1",
        RouteDecision(
            RouteTarget.AFTERSALES, Intent.AFTER_SALES,
            {"order_id": "88001"},
        ),
        RouteTarget.AFTERSALES,
        "订单88001我要退款",
    )

    state = await memory.update(
        "s1",
        RouteDecision(RouteTarget.PRESALES, Intent.PRODUCT),
        RouteTarget.PRESALES,
        "推荐一个充电宝",
    )

    assert state["domain"] == "presales"
    assert state["slots"] == {}


async def test_non_agent_exchange_is_persisted(tmp_path):
    session_store = SessionStore(tmp_path)
    memory = SessionMemoryManager(ContextStore(), session_store)

    await memory.record_exchange("fast:1", "你好", "你好呀～")

    assert await session_store.load_history("fast:1") == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好呀～"},
    ]


async def test_meta_only_session_is_listed_for_restart_restore(tmp_path):
    session_store = SessionStore(tmp_path)
    await session_store.save_context("fast:only", {"intent": "greeting"})

    assert await session_store.list_sessions() == ["fast_only"]

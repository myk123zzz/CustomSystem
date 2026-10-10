from core.context_store import ContextStore
from core.session_state import Phase, SessionContext


def test_waiting_session_skips_router_until_info_received():
    store = ContextStore()
    session = SessionContext(store, "web:test")

    session.agent_is_waiting("订单号", intent="退款")

    assert session.phase is Phase.COLLECTING_INFO
    assert session.should_skip_router() is True
    assert session.waiting_for == "订单号"
    assert session.intent == "退款"

    session.info_received()

    assert session.phase is Phase.NORMAL
    assert session.should_skip_router() is False
    assert session.waiting_for == ""
    assert session.intent == ""


def test_handoff_is_a_distinct_session_phase():
    store = ContextStore()
    session = SessionContext(store, "web:test")

    session.handoff()

    assert session.phase is Phase.HANDOFF
    assert session.should_skip_router() is False


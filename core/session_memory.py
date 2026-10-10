"""Session memory coordinated from RouteDecision instead of reclassification."""

from __future__ import annotations

import asyncio

from core.intent_router import Intent
from core.router import RouteDecision, RouteTarget
from core.session_state import Phase, SessionContext


class SessionMemoryManager:
    """Maintain current task state and persist it through the existing store."""

    def __init__(self, context_store, session_store=None):
        self.context_store = context_store
        self.session_store = session_store
        self._history_locks: dict[str, asyncio.Lock] = {}

    def context(self, session_key: str) -> dict:
        return self.context_store.get_all(session_key)

    def prompt_text(self, session_key: str) -> str:
        state = self.context(session_key)
        lines = []
        if state.get("domain"):
            lines.append(f"- 当前业务域: {state['domain']}")
        if state.get("intent"):
            lines.append(f"- 当前意图: {state['intent']}")
        slots = state.get("slots") or {}
        if slots.get("order_id"):
            lines.append(f"- 当前订单号: {slots['order_id']}")
        if state.get("phase") == Phase.COLLECTING_INFO.value:
            lines.append(f"- 正在等待用户提供: {state.get('waiting_for', '信息')}")
        return "\n".join(lines)

    async def update(
        self,
        session_key: str,
        decision: RouteDecision,
        final_target: RouteTarget,
        message: str,
    ) -> dict:
        session = SessionContext(self.context_store, session_key)
        previous_domain = self.context_store.get(session_key, "domain", "")
        domain = self._domain_for(final_target, decision.intent)
        slots = dict(self.context_store.get(session_key, "slots", {}) or {})
        if previous_domain and domain and previous_domain != domain:
            slots = self._slots_for_domain(slots, domain)
        if domain:
            self.context_store.set(session_key, "domain", domain)
        self.context_store.set(session_key, "intent", decision.intent.value)

        slots.update(decision.entities)
        self.context_store.set(session_key, "slots", slots)

        if final_target is RouteTarget.HUMAN:
            session.handoff()
        elif decision.intent is Intent.AFTER_SALES:
            action = self._after_sales_action(message)
            if action:
                slots["action"] = action
            self.context_store.set(session_key, "slots", slots)
            if not slots.get("order_id"):
                session.agent_is_waiting("订单号", intent=decision.intent.value)
            elif session.phase is Phase.COLLECTING_INFO and session.waiting_for == "订单号":
                session.phase = Phase.NORMAL
                self.context_store.set(session_key, "waiting_for", "")
                self.context_store.set(session_key, "intent", decision.intent.value)
            else:
                session.phase = Phase.NORMAL
                self.context_store.set(session_key, "waiting_for", "")
        elif session.phase is not Phase.HANDOFF:
            session.phase = Phase.NORMAL

        state = self.context(session_key)
        if self.session_store is not None and state:
            await self.session_store.save_context(session_key, state)
        return state

    async def record_exchange(
        self,
        session_key: str,
        user_message: str,
        assistant_message: str,
        *,
        max_messages: int = 40,
    ) -> None:
        """Persist non-Agent exchanges so every execution path has history."""
        if self.session_store is None:
            return
        lock = self._history_locks.setdefault(session_key, asyncio.Lock())
        async with lock:
            history = await self.session_store.load_history(
                session_key, max_messages=max_messages
            )
            history.extend([
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message},
            ])
            await self.session_store.save_history(
                session_key, history[-max_messages:]
            )

    @staticmethod
    def _slots_for_domain(slots: dict, domain: str) -> dict:
        if domain == RouteTarget.PRESALES.value:
            return {
                key: value for key, value in slots.items()
                if key not in {"order_id", "tracking_no", "phone_tail", "action"}
            }
        if domain == RouteTarget.IN_SALES.value:
            return {key: value for key, value in slots.items() if key != "action"}
        return slots

    @staticmethod
    def _after_sales_action(message: str) -> str | None:
        if any(word in message for word in ("换货", "我要换", "想换")):
            return "换货"
        if any(word in message for word in ("退款", "退钱")):
            return "退款"
        if any(word in message for word in ("退货", "我要退", "想退", "帮我退")):
            return "退货"
        return None

    @staticmethod
    def _domain_for(target: RouteTarget, intent: Intent) -> str:
        if target in {RouteTarget.PRESALES, RouteTarget.IN_SALES, RouteTarget.AFTERSALES}:
            return target.value
        if intent in {Intent.GREETING, Intent.FAQ, Intent.PRODUCT}:
            return RouteTarget.PRESALES.value
        if intent in {Intent.ORDER_QUERY, Intent.LOGISTICS}:
            return RouteTarget.IN_SALES.value
        if intent in {Intent.AFTER_SALES, Intent.COMPLAINT}:
            return RouteTarget.AFTERSALES.value
        return ""

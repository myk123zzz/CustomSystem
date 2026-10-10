"""Unified request router for FastPath and domain-specific agents.

The router classifies a request and returns a decision. It deliberately does
not execute tools or build a customer-facing reply; those responsibilities
belong to FastPathExecutor and the selected agent runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any

from core.intent_router import Intent, _classify_layer_1_2


class RouteTarget(str, Enum):
    FAST_PATH = "fast_path"
    PRESALES = "presales"
    IN_SALES = "in_sales"
    AFTERSALES = "aftersales"
    HUMAN = "human"


@dataclass(frozen=True)
class RouteDecision:
    target: RouteTarget
    intent: Intent
    entities: dict[str, str] = field(default_factory=dict)
    confidence: float = 1.0
    reason: str = ""


_COMPLEX_PRODUCT_WORDS = {
    "推荐", "对比", "哪个好", "怎么选", "适合", "预算", "需求", "搭配",
}
_DIRECT_HUMAN_WORDS = {
    "人工", "负责人", "经理", "消协", "监管", "举报", "投诉",
}

_LLM_ROUTE_PROMPT = """判断用户问题应交给哪个客服部门，只输出一个标签：
presales | in_sales | aftersales | human

presales: 商品选择、推荐、对比、购买前咨询
in_sales: 订单、支付、发货、物流、履约异常
aftersales: 退货、退款、换货、保修、一般售后问题
human: 明确要求人工、严重投诉或高风险问题

用户消息: {message}
标签:"""


class Router:
    """Return a RouteDecision without executing business operations."""

    def __init__(self, provider=None, session_factory=None):
        self.provider = provider
        self._get_session = session_factory
        self._target_counts = {target.value: 0 for target in RouteTarget}
        self._intent_counts = {intent.value: 0 for intent in Intent}
        self._latency: dict[str, list[float]] = {}
        self._handoffs = 0
        self._llm_classify_used = 0

    async def route(self, message: str, session_key: str = "") -> RouteDecision:
        started = time.perf_counter()
        msg = message.strip()

        active = self._active_session_decision(msg, session_key)
        if active is not None:
            return self._record(active, started)

        intent, entities = _classify_layer_1_2(msg)
        domain_followup = self._domain_followup_decision(
            intent, entities, session_key
        )
        if domain_followup is not None:
            return self._record(domain_followup, started)
        deterministic = self._deterministic_decision(msg, intent, entities)
        if deterministic is not None:
            return self._record(deterministic, started)

        return self._record(await self._llm_decision(msg, entities), started)

    def _record(self, decision: RouteDecision, started: float) -> RouteDecision:
        self._target_counts[decision.target.value] += 1
        self._intent_counts[decision.intent.value] += 1
        if decision.reason in {"llm_fallback", "invalid_llm_route"}:
            self._llm_classify_used += 1
        elapsed_ms = (time.perf_counter() - started) * 1000
        self._latency.setdefault(decision.intent.value, []).append(elapsed_ms)
        return decision

    def record_latency(self, intent: str, latency_ms: float) -> None:
        """Record end-to-end latency while preserving the existing admin API."""
        self._latency.setdefault(intent, []).append(latency_ms)

    def record_handoff(self) -> None:
        self._handoffs += 1

    @property
    def stats(self) -> dict[str, Any]:
        avg_by_intent = {
            intent: round(sum(values) / len(values), 1)
            for intent, values in self._latency.items()
            if values
        }
        total = sum(self._target_counts.values())
        divisor = max(total, 1)
        agent_calls = sum(
            self._target_counts[target.value]
            for target in (RouteTarget.PRESALES, RouteTarget.IN_SALES, RouteTarget.AFTERSALES)
        )
        fast_path_calls = self._target_counts[RouteTarget.FAST_PATH.value]
        all_latencies = [value for values in self._latency.values() for value in values]
        by_intent = {
            intent: {
                "count": count,
                "pct": round(count / divisor * 100, 1),
                "avg_ms": avg_by_intent.get(intent, 0.0),
            }
            for intent, count in self._intent_counts.items()
        }
        return {
            # Compatibility fields used by the existing admin page.
            "total_requests": total,
            "by_intent": by_intent,
            "agent_calls": agent_calls,
            "agent_pct": round(agent_calls / divisor * 100, 1),
            "direct_pct": round(fast_path_calls / divisor * 100, 1),
            "avg_latency_ms": round(
                sum(all_latencies) / max(len(all_latencies), 1), 1
            ),
            "llm_classify_used": self._llm_classify_used,
            # New detailed dimensions.
            "targets": dict(self._target_counts),
            "intents": dict(self._intent_counts),
            "avg_latency_by_intent_ms": avg_by_intent,
            "handoffs": self._handoffs,
        }

    def _active_session_decision(
        self,
        message: str,
        session_key: str,
    ) -> RouteDecision | None:
        if not self._get_session or not session_key:
            return None

        session = self._get_session(session_key)
        if not session.should_skip_router():
            return None

        intent_text = session.intent or "售后"
        _surface_intent, entities = _classify_layer_1_2(message)
        return RouteDecision(
            target=RouteTarget.AFTERSALES,
            intent=Intent.AFTER_SALES,
            entities=entities,
            confidence=1.0,
            reason=f"continue_active_session:{intent_text}",
        )

    def _domain_followup_decision(
        self,
        surface_intent: Intent,
        entities: dict[str, str],
        session_key: str,
    ) -> RouteDecision | None:
        """Keep vague follow-ups in an established domain after slot collection."""
        if surface_intent is not Intent.COMPLEX or not self._get_session or not session_key:
            return None
        session = self._get_session(session_key)
        domain = session.store.get(session_key, "domain", "")
        if domain == RouteTarget.AFTERSALES.value:
            return RouteDecision(
                RouteTarget.AFTERSALES,
                Intent.AFTER_SALES,
                entities,
                0.9,
                "continue_domain:aftersales",
            )
        return None

    @staticmethod
    def _deterministic_decision(
        message: str,
        intent: Intent,
        entities: dict[str, str],
    ) -> RouteDecision | None:
        if any(word in message for word in _DIRECT_HUMAN_WORDS):
            return RouteDecision(
                RouteTarget.HUMAN, Intent.COMPLAINT, entities, 1.0, "explicit_handoff"
            )

        if intent in {Intent.GREETING, Intent.FAQ}:
            return RouteDecision(RouteTarget.FAST_PATH, intent, entities, 1.0, "fixed_workflow")

        if intent is Intent.PRODUCT:
            if any(word in message for word in _COMPLEX_PRODUCT_WORDS):
                return RouteDecision(
                    RouteTarget.PRESALES, intent, entities, 0.95, "complex_product_request"
                )
            return RouteDecision(RouteTarget.FAST_PATH, intent, entities, 1.0, "simple_product_lookup")

        if intent is Intent.ORDER_QUERY:
            target = RouteTarget.FAST_PATH if entities.get("order_id") else RouteTarget.IN_SALES
            reason = "complete_order_lookup" if target is RouteTarget.FAST_PATH else "missing_order_entity"
            return RouteDecision(target, intent, entities, 1.0, reason)

        if intent is Intent.LOGISTICS:
            complete = bool(entities.get("order_id") or entities.get("tracking_no"))
            target = RouteTarget.FAST_PATH if complete else RouteTarget.IN_SALES
            reason = "complete_logistics_lookup" if complete else "logistics_requires_reasoning"
            return RouteDecision(target, intent, entities, 1.0, reason)

        if intent is Intent.AFTER_SALES:
            return RouteDecision(RouteTarget.AFTERSALES, intent, entities, 1.0, "after_sales_workflow")

        if intent is Intent.COMPLAINT:
            return RouteDecision(RouteTarget.HUMAN, intent, entities, 1.0, "complaint_handoff")

        return None

    async def _llm_decision(self, message: str, entities: dict[str, str]) -> RouteDecision:
        if self.provider is None:
            return RouteDecision(
                RouteTarget.PRESALES,
                Intent.COMPLEX,
                entities,
                0.4,
                "no_provider_default",
            )

        try:
            response = await self.provider.chat(
                messages=[{
                    "role": "user",
                    "content": _LLM_ROUTE_PROMPT.format(message=message),
                }],
                tools=None,
            )
            raw = (response.content or "").strip().lower()
        except Exception:
            raw = ""

        mapping: dict[str, tuple[RouteTarget, Intent]] = {
            "presales": (RouteTarget.PRESALES, Intent.PRODUCT),
            "in_sales": (RouteTarget.IN_SALES, Intent.ORDER_QUERY),
            "aftersales": (RouteTarget.AFTERSALES, Intent.AFTER_SALES),
            "human": (RouteTarget.HUMAN, Intent.COMPLAINT),
        }
        for label, (target, intent) in mapping.items():
            if label in raw:
                return RouteDecision(target, intent, entities, 0.75, "llm_fallback")

        return RouteDecision(
            RouteTarget.HUMAN,
            Intent.COMPLEX,
            entities,
            0.0,
            "invalid_llm_route",
        )

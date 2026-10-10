"""Deterministic scoring for routes, tools, cost, and response contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from evaluation.dataset import EvalCase


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    passed: bool
    checks: dict[str, bool]
    actual_target: str
    actual_intent: str


@dataclass(frozen=True)
class EvalReport:
    total: int
    passed: int
    pass_rate: float
    route_accuracy: float
    tool_accuracy: float
    llm_budget_accuracy: float
    session_accuracy: float
    handoff_accuracy: float
    category_pass_rate: dict[str, float]
    results: list[CaseResult]


def evaluate_case(case: EvalCase, result) -> CaseResult:
    tools = set(result.tools_called)
    state = result.session_state or {}
    slots = state.get("slots") or {}
    checks = {
        "route": result.final_target.value == case.expected_target,
        "intent": (
            case.expected_intent is None
            or result.decision.intent.value == case.expected_intent
            or result.decision.intent.value in case.accepted_intents
        ),
        "required_tools": set(case.required_tools) <= tools,
        "forbidden_tools": not (set(case.forbidden_tools) & tools),
        "min_tool_calls": case.min_tool_calls is None or len(result.tools_called) >= case.min_tool_calls,
        "max_tool_calls": case.max_tool_calls is None or len(result.tools_called) <= case.max_tool_calls,
        "llm_budget": case.max_llm_calls is None or result.llm_calls <= case.max_llm_calls,
        "reply_contract": all(word in result.reply for word in case.reply_keywords),
        "handoff": case.expected_handoff is None or (
            result.final_target.value == "human"
        ) == case.expected_handoff,
        "phase": case.expected_phase is None or state.get("phase") == case.expected_phase,
        "slots": all(slots.get(key) == value for key, value in case.expected_slots.items()),
        "absent_slots": all(key not in slots for key in case.absent_slots),
    }
    return CaseResult(
        case_id=case.id,
        passed=all(checks.values()),
        checks=checks,
        actual_target=result.final_target.value,
        actual_intent=result.decision.intent.value,
    )


def evaluate_results(pairs: Iterable[tuple[EvalCase, object]]) -> EvalReport:
    materialized = list(pairs)
    results = [evaluate_case(case, result) for case, result in materialized]
    total = len(results)
    passed = sum(item.passed for item in results)
    route_ok = sum(item.checks["route"] and item.checks["intent"] for item in results)
    tool_ok = sum(
        item.checks["required_tools"] and item.checks["forbidden_tools"]
        and item.checks["min_tool_calls"] and item.checks["max_tool_calls"]
        for item in results
    )
    llm_ok = sum(item.checks["llm_budget"] for item in results)
    session_ok = sum(
        item.checks["phase"] and item.checks["slots"] and item.checks["absent_slots"]
        for item in results
    )
    handoff_ok = sum(item.checks["handoff"] for item in results)
    divisor = total or 1
    categories: dict[str, list[bool]] = {}
    for (case, _result), scored in zip(materialized, results):
        categories.setdefault(case.category, []).append(scored.passed)
    category_rates = {
        name: sum(values) / len(values) for name, values in categories.items()
    }
    return EvalReport(
        total, passed, passed / divisor, route_ok / divisor, tool_ok / divisor,
        llm_ok / divisor, session_ok / divisor, handoff_ok / divisor,
        category_rates, results,
    )

from types import SimpleNamespace
from dataclasses import dataclass

from core.context_store import ContextStore
from core.fast_path import FastPathExecutor
from core.router import Intent, RouteDecision, RouteTarget
from core.router import Router
from core.service import CustomerServiceEngine, ServiceResult
from core.session_memory import SessionMemoryManager
from core.session_state import SessionContext
from core.trace import TraceStore
from evaluation.dataset import load_cases
from evaluation.deterministic import build_deterministic_engine
from evaluation.metrics import evaluate_case, evaluate_results
from evaluation.sandbox import EvaluationSandbox


def result(target="fast_path", intent="greeting", tools=None, llm_calls=0, reply="你好，我是小闪"):
    return ServiceResult(
        reply=reply,
        decision=RouteDecision(RouteTarget(target), Intent(intent), 1.0, "rule"),
        final_target=RouteTarget(target), tools_called=tools or [], llm_calls=llm_calls,
        latency_ms=1, session_state={"phase": "normal"},
    )


def test_dataset_is_versioned_and_covers_all_targets():
    cases = load_cases()
    assert len(cases) >= 30
    assert {case.expected_target for case in cases} == {
        "fast_path", "presales", "in_sales", "aftersales", "human"
    }


def test_metrics_explain_individual_failures():
    case = load_cases()[0]
    scored = evaluate_case(case, result(llm_calls=1))
    assert not scored.passed
    assert scored.checks["route"]
    assert not scored.checks["llm_budget"]


def test_report_aggregates_scores():
    case = load_cases()[0]
    report = evaluate_results([(case, result())])
    assert report.total == report.passed == 1
    assert report.pass_rate == report.route_accuracy == report.tool_accuracy == 1.0


async def test_sandbox_runs_all_turns_on_one_engine():
    calls = []
    fake_engine = SimpleNamespace(process=_process)

    # Bind after declaration to keep the fake intentionally tiny.
    async def process(message, session_key):
        calls.append((message, session_key))
        return result(target="aftersales", intent="after_sales")

    fake_engine.process = process
    case = next(
        case for case in load_cases()
        if case.id == "aftersales_multiturn_order"
    )
    actual = await EvaluationSandbox(lambda: fake_engine).run(case)
    assert actual.final_target is RouteTarget.AFTERSALES
    assert [item[0] for item in calls] == case.turns
    assert len({item[1] for item in calls}) == 1


class EvalTools:
    async def execute(self, name, params):
        if name == "order_query":
            order_id = params.get("order_id") or "88001"
            return f"订单{order_id}状态正常。"
        replies = {
            "faq_lookup": "支持7天无理由退货。",
            "request_human": "已转人工客服。",
        }
        return replies.get(name, "工具完成")


@dataclass
class EvalTurn:
    final_content: str
    tools_called: list[str]
    llm_calls: int = 2
    stop_reason: str = "completed"


class EvalAgents:
    async def execute(self, *, target, **kwargs):
        tool_by_target = {
            RouteTarget.PRESALES: "rag_search",
            RouteTarget.IN_SALES: "order_query",
            RouteTarget.AFTERSALES: "order_query",
        }
        return EvalTurn("专业客服已处理。", [tool_by_target[target]])


class EvalKnowledgeBase:
    def search_products(self, query, n_results=3):
        return [{
            "name": "Qi2 超薄磁吸充电宝 5000mAh",
            "content": "Qi2 磁吸充电宝，售价149元。",
            "score": 0.9,
        }]


def build_eval_engine():
    return build_deterministic_engine()


async def test_versioned_suite_passes_through_real_router_and_engine():
    cases = load_cases()
    pairs = await EvaluationSandbox(build_eval_engine).run_all(cases)
    report = evaluate_results(pairs)
    failures = {
        item.case_id: item.checks for item in report.results if not item.passed
    }
    assert report.passed == report.total, failures


async def _process(*args, **kwargs):
    raise AssertionError("replaced in test")

"""Application service shared by FastAPI and deterministic test sandboxes."""

from __future__ import annotations

import time
from dataclasses import dataclass
from dataclasses import field

from core.router import RouteDecision, RouteTarget
from core.trace import RequestTrace


@dataclass(frozen=True)
class ServiceResult:
    reply: str
    decision: RouteDecision
    final_target: RouteTarget
    tools_called: list[str]
    llm_calls: int
    latency_ms: int
    status: str = "completed"
    error: str | None = None
    session_state: dict = field(default_factory=dict)

    @property
    def used_agent(self) -> bool:
        return self.final_target in {
            RouteTarget.PRESALES,
            RouteTarget.IN_SALES,
            RouteTarget.AFTERSALES,
        }


class CustomerServiceEngine:
    """Orchestrate Router, FastPath, one domain Agent, memory, and trace."""

    def __init__(self, router, fast_path, domain_agents, tools, session_memory, trace_store):
        self.router = router
        self.fast_path = fast_path
        self.domain_agents = domain_agents
        self.tools = tools
        self.session_memory = session_memory
        self.trace_store = trace_store

    async def process(
        self,
        message: str,
        session_key: str,
        *,
        profile_text: str = "",
    ) -> ServiceResult:
        started = time.perf_counter()
        context_text = self.session_memory.prompt_text(session_key)
        decision = await self.router.route(message, session_key=session_key)
        target = decision.target
        tools_called: list[str] = []
        llm_calls = int(decision.reason in {"llm_fallback", "invalid_llm_route"})
        status = "completed"
        error = None

        if target is RouteTarget.FAST_PATH:
            fast_result = await self.fast_path.execute(decision, message)
            tools_called.extend(fast_result.tools_called)
            if fast_result.handled:
                reply = fast_result.reply
            else:
                target = fast_result.fallback_target or RouteTarget.HUMAN
                error = fast_result.error

        if target is RouteTarget.HUMAN:
            reply = await self.tools.execute(
                "request_human",
                {"reason": "用户明确要求人工或请求需要人工审核"},
            )
            tools_called.append("request_human")
            self.router.record_handoff()
        elif target is not RouteTarget.FAST_PATH:
            turn = await self.domain_agents.execute(
                target=target,
                message=message,
                session_key=session_key,
                profile_text=profile_text,
                context_text=context_text,
            )
            reply = turn.final_content or "(无法生成回复)"
            tools_called.extend(turn.tools_called)
            llm_calls += turn.llm_calls
            status = turn.stop_reason

        latency_ms = int((time.perf_counter() - started) * 1000)
        self.router.record_latency(decision.intent.value, latency_ms)
        session_state = await self.session_memory.update(
            session_key, decision, target, message
        )
        if target in {RouteTarget.FAST_PATH, RouteTarget.HUMAN}:
            await self.session_memory.record_exchange(
                session_key, message, reply
            )
        self.trace_store.append(RequestTrace(
            session_key=session_key,
            target=target.value,
            intent=decision.intent.value,
            tools_called=tools_called,
            llm_calls=llm_calls,
            latency_ms=latency_ms,
            status=status,
            error=error,
        ))
        return ServiceResult(
            reply=reply,
            decision=decision,
            final_target=target,
            tools_called=tools_called,
            llm_calls=llm_calls,
            latency_ms=latency_ms,
            status=status,
            error=error,
            session_state=session_state,
        )

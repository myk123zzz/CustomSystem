"""Runs multi-turn EvalCases through the same engine used by FastAPI."""

from __future__ import annotations

from dataclasses import replace

from evaluation.dataset import EvalCase


class EvaluationSandbox:
    def __init__(self, engine_factory):
        self.engine_factory = engine_factory

    async def run(self, case: EvalCase):
        engine = self.engine_factory()
        result = None
        tools_called: list[str] = []
        llm_calls = 0
        for turn in case.turns:
            result = await engine.process(turn, f"eval:{case.id}")
            tools_called.extend(result.tools_called)
            llm_calls += result.llm_calls
        if result is None:
            raise ValueError(f"EvalCase {case.id!r} has no turns")
        return replace(
            result,
            tools_called=tools_called,
            llm_calls=llm_calls,
        )

    async def run_all(self, cases: list[EvalCase]):
        return [(case, await self.run(case)) for case in cases]

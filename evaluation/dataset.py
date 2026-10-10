"""Versioned, product-owned evaluation cases (independent of Ecom code)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class EvalCase:
    id: str
    turns: list[str]
    expected_target: str
    category: str = "general"
    description: str = ""
    expected_intent: str | None = None
    accepted_intents: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    forbidden_tools: list[str] = field(default_factory=list)
    min_tool_calls: int | None = None
    max_tool_calls: int | None = None
    max_llm_calls: int | None = None
    reply_keywords: list[str] = field(default_factory=list)
    expected_handoff: bool | None = None
    expected_phase: str | None = None
    expected_slots: dict[str, str] = field(default_factory=dict)
    absent_slots: list[str] = field(default_factory=list)


def load_cases(path: str | Path | None = None) -> list[EvalCase]:
    source = Path(path) if path else Path(__file__).with_name("cases.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    return [EvalCase(**item) for item in payload]

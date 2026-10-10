"""Small in-process trace model for requests, agents, and tools."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


@dataclass(frozen=True)
class RequestTrace:
    session_key: str
    target: str
    intent: str
    tools_called: list[str] = field(default_factory=list)
    llm_calls: int = 0
    latency_ms: int = 0
    status: str = "completed"
    error: str | None = None
    request_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class TraceStore:
    def __init__(self, maxlen: int = 500):
        self._items: deque[RequestTrace] = deque(maxlen=maxlen)

    def append(self, trace: RequestTrace) -> None:
        self._items.append(trace)

    def recent(self, limit: int = 100) -> list[dict]:
        items = list(self._items)[-max(limit, 0):]
        return [asdict(item) for item in items]

    def __len__(self) -> int:
        return len(self._items)


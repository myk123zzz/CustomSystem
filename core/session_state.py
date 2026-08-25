"""
会话阶段跟踪
============
不用复杂的状态机概念——就是一个标记位，记录"Agent 是不是在等用户回复"。

为什么需要这个？
  当 Agent 问"请提供你的订单号"，用户回复 "88001" 时——
  如果路由器正常工作，"88001" 会被当作新的订单查询拦截下来，
  Agent 就收不到用户的回复了。所以这时需要跳过路由。

三个阶段：
  normal          — 正常对话，路由器工作
  collecting_info — Agent 问了问题在等回复，跳过路由
  handoff         — 已转人工
"""

from enum import Enum


class Phase(str, Enum):
    NORMAL = "normal"
    COLLECTING_INFO = "collecting"   # Agent 在等用户提供信息
    HANDOFF = "handoff"


class SessionContext:
    """单个会话的上下文管理——跟踪"当前在干什么"。

    这不是复杂的状态机，就是三个辅助方法。
    """

    def __init__(self, store, session_key: str):
        """
        Args:
            store: ContextStore 实例
            session_key: 会话标识
        """
        self.store = store
        self.session_key = session_key

    # ── 当前阶段 ──────────────────────────────────────────────────────

    @property
    def phase(self) -> Phase:
        raw = self.store.get(self.session_key, "phase", "normal")
        try:
            return Phase(raw)
        except ValueError:
            return Phase.NORMAL

    @phase.setter
    def phase(self, value: Phase):
        self.store.set(self.session_key, "phase", value.value)

    # ── 便捷操作 ──────────────────────────────────────────────────────

    def agent_is_waiting(self, for_what: str, intent: str = ""):
        """Agent 向用户提了问题，现在等回复。

        例如：agent_is_waiting("订单号", intent="退货")
        → 路由器跳过，下一条用户消息直接给 Agent
        """
        self.phase = Phase.COLLECTING_INFO
        self.store.set(self.session_key, "waiting_for", for_what)
        if intent:
            self.store.set(self.session_key, "intent", intent)

    def info_received(self):
        """用户提供了信息，恢复正常。"""
        self.phase = Phase.NORMAL
        self.store.set(self.session_key, "waiting_for", "")
        self.store.set(self.session_key, "intent", "")

    def handoff(self):
        """转人工。"""
        self.phase = Phase.HANDOFF

    def should_skip_router(self) -> bool:
        """当前消息是否应该跳过意图路由。

        只有 Agent 正在等用户回复时才跳过——
        因为用户的回复可能被路由器误判为新的查询。
        """
        return self.phase == Phase.COLLECTING_INFO

    @property
    def waiting_for(self) -> str:
        """Agent 在等什么（订单号/手机号/确认...）"""
        return self.store.get(self.session_key, "waiting_for", "")

    @property
    def intent(self) -> str:
        """当前事务意图（退货/退款/换货...）"""
        return self.store.get(self.session_key, "intent", "")

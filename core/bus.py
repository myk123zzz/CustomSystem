"""
MessageBus — 异步消息总线
===========================
借鉴 nanobot/bus/queue.py 的 MessageBus 设计。

核心设计（来自 nanobot）：
  - 生产者-消费者模式，解耦消息收发两端
  - 两个 asyncio.Queue：inbound（收消息）+ outbound（发回复）
  - 极其精简——一共 4 个方法

当前实现：asyncio.Queue（内存队列）
后续升级：Redis Streams（加持久化 + 消费确认，接口不变）

设计原则：
  发消息的（Channel/WebUI）不感知谁在处理，
  处理消息的（AgentLoop）不感知谁在收发。
  中间全靠 MessageBus 串联。
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ============================================================================
# 消息数据类 —— 借鉴 nanobot/bus/events.py
# ============================================================================

@dataclass
class InboundMessage:
    """从外部收到的用户消息"""
    content: str                            # 消息正文
    session_key: str                        # 会话标识（同一用户同一会话共享 key）
    channel: str = "cli"                    # 来源渠道（cli / web / telegram ...）
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutboundMessage:
    """要发回给用户的回复消息"""
    content: str                            # 回复正文
    channel: str = "cli"                    # 目标渠道
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# 消息总线 —— 借鉴 nanobot/bus/queue.py
# ============================================================================

class MessageBus:
    """异步消息总线。

    借鉴 nanobot 的同名类。两个 asyncio.Queue：
      inbound  — 用户 → Agent
      outbound — Agent → 用户

    后续升级 Redis Streams 时，只需改这 4 个方法的内部实现，
    外部调用者（AgentLoop、Channel）零改动。
    """

    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    # ---- 入站（用户 → Agent） ----

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """发布一条入站消息（Channel 调用）"""
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """消费一条入站消息（AgentLoop 调用）。
        队列为空时会阻塞等待，不消耗 CPU。
        """
        return await self.inbound.get()

    # ---- 出站（Agent → 用户） ----

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """发布一条出站消息（AgentLoop 调用）"""
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """消费一条出站消息（Channel 调用）。
        队列为空时会阻塞等待。
        """
        return await self.outbound.get()

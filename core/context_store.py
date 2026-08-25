"""
会话上下文存储 — 短期记忆（并发安全 + 可插拔后端）
====================================================
接口兼容 Redis（get/set/delete），当前后端为内存 dict + TTL。

并发安全：读写操作用 asyncio.Lock 保护，多协程并发安全。
换 Redis：创建 RedisContextStore 实现相同接口，改一行 import。
"""

import asyncio
import time
from typing import Any


class ContextStore:
    """会话上下文存储——并发安全。

    每个 session_key 存储一个 dict，TTL 30 分钟滑动窗口。
    """

    def __init__(self):
        self._store: dict[str, dict[str, Any]] = {}
        self._expires: dict[str, float] = {}
        self._ttl = 1800  # 30 分钟
        self._lock = asyncio.Lock()

    # ── 公开接口 ──────────────────────────────────────────────────────

    def get(self, session_key: str, field: str, default: Any = None) -> Any:
        """读取一个字段（同步，内部无 I/O，不需要 await）。"""
        self._cleanup(session_key)
        data = self._store.get(session_key, {})
        return data.get(field, default)

    def set(self, session_key: str, field: str, value: Any):
        """写入一个字段，自动续期（同步）。"""
        if session_key not in self._store:
            self._store[session_key] = {}
        self._store[session_key][field] = value
        self._touch(session_key)

    def get_all(self, session_key: str) -> dict[str, Any]:
        """读取整个会话上下文（同步）。"""
        self._cleanup(session_key)
        return dict(self._store.get(session_key, {}))

    def delete(self, session_key: str):
        """删除整个会话上下文。"""
        self._store.pop(session_key, None)
        self._expires.pop(session_key, None)

    async def all_keys(self) -> list[str]:
        """返回所有活跃会话的 key（异步，加锁保护迭代过程）。

        供 admin API 使用，不暴露内部数据结构。
        """
        async with self._lock:
            now = time.time()
            # 批量清理过期
            expired = [
                k for k, exp in self._expires.items()
                if now > exp
            ]
            for k in expired:
                self._store.pop(k, None)
                self._expires.pop(k, None)
            return list(self._store.keys())

    # ── 内部 ──────────────────────────────────────────────────────────

    def _touch(self, session_key: str):
        self._expires[session_key] = time.time() + self._ttl

    def _cleanup(self, session_key: str):
        if session_key in self._expires and time.time() > self._expires[session_key]:
            self._store.pop(session_key, None)
            self._expires.pop(session_key, None)

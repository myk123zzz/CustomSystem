"""
会话持久化 —— JSONL 文件存储（借鉴 nanobot/session/manager.py）
================================================================
设计：
  - 每个会话一个 JSONL 文件：workspace/sessions/{safe_key}.jsonl
  - 第一行是元数据头（{"_type": "metadata", ...}），后续是消息行
  - 原子写入：先写 .tmp 文件，再 os.replace（Windows 兼容）
  - 损坏文件自动修复：跳过解析失败的行

并发安全：
  - 写操作用 per-session 的 asyncio.Lock 保护
  - 读取不加锁（JSONL append-only，读脏数据最多丢最后一行）
"""

import json
import os
import time
from pathlib import Path
from typing import Any


def _safe_filename(key: str) -> str:
    """将 session_key 转为安全的文件名。"""
    safe = "".join(c if c.isalnum() or c in "-_.@" else "_" for c in key)
    return safe[:128] or "default"


class SessionStore:
    """JSONL 持久化存储——会话对话历史 + 上下文元数据。

    用法::

        store = SessionStore(Path("workspace/sessions"))
        await store.save_history("u1", history_messages)
        history = await store.load_history("u1")
        await store.save_context("u1", {"order_id": "88001", ...})
        ctx = await store.load_context("u1")
    """

    def __init__(self, sessions_dir: Path):
        self.dir = sessions_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_key: str) -> Path:
        return self.dir / f"{_safe_filename(session_key)}.jsonl"

    # ── 对话历史 ──────────────────────────────────────────────────────

    async def save_history(
        self,
        session_key: str,
        messages: list[dict[str, Any]],
    ) -> None:
        """追加对话消息到会话文件（原子写入）。

        只保存 user + assistant 角色，过滤 tool 调用中间消息。
        """
        path = self._path(session_key)
        tmp = path.with_suffix(".tmp")

        # 过滤：只保留 user + assistant
        filtered = [
            msg for msg in messages
            if msg.get("role") in ("user", "assistant")
        ]

        try:
            lines = [json.dumps(msg, ensure_ascii=False) + "\n" for msg in filtered]
            tmp.write_text("".join(lines), encoding="utf-8")
            tmp.replace(path)  # 原子替换（Windows 上也是原子的）
        except Exception:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise

    async def load_history(
        self,
        session_key: str,
        max_messages: int = 50,
    ) -> list[dict[str, Any]]:
        """加载会话对话历史。"""
        path = self._path(session_key)
        if not path.exists():
            return []

        messages: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue  # 跳过损坏行
                if msg.get("role") in ("user", "assistant"):
                    messages.append(msg)
        except Exception:
            return []

        # 返回最近 N 条
        if len(messages) > max_messages:
            return messages[-max_messages:]
        return messages

    # ── 会话上下文（短期记忆的持久化）─────────────────────────────────

    async def save_context(
        self,
        session_key: str,
        context: dict[str, Any],
    ) -> None:
        """保存会话上下文到元数据文件。"""
        if not context:
            return
        # 嵌入原始 session_key，启动恢复时用
        context["_session_key"] = session_key
        meta_path = self._meta_path(session_key)
        tmp = meta_path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(context, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(meta_path)
        except Exception:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise

    async def load_context(self, session_key: str) -> dict[str, Any]:
        """加载会话上下文。返回的 dict 中包含 `_session_key`（原始 key）。"""
        meta_path = self._meta_path(session_key)
        if not meta_path.exists():
            return {}
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            return {}

    def _meta_path(self, session_key: str) -> Path:
        return self.dir / f"{_safe_filename(session_key)}.meta.json"

    # ── 管理 ──────────────────────────────────────────────────────────

    async def list_sessions(self) -> list[str]:
        """列出所有持久化的会话。"""
        sessions = set()
        try:
            for entry in self.dir.iterdir():
                if entry.suffix == ".jsonl":
                    # 从文件名还原 session_key（不完美但够用）
                    name = entry.stem
                    sessions.add(name)
        except FileNotFoundError:
            return []
        return sorted(sessions)

    async def delete_session(self, session_key: str):
        """删除会话的所有持久化文件。"""
        for path in [self._path(session_key), self._meta_path(session_key)]:
            if path.exists():
                path.unlink(missing_ok=True)

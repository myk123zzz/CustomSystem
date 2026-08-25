"""
AgentLoop — Agent 主循环（借鉴 nanobot/agent/runner.py 的治理策略）
=====================================================================

核心设计：
  1. ReAct 循环：LLM 返回 tool_calls → 执行工具 → 结果追加到 messages → 继续推理
  2. 上下文治理（借鉴 nanobot AgentRunner._run_core）：
     - 工具结果截断（max_tool_result_chars），防止大结果撑爆上下文窗口
     - 工具结果摘要（microcompact），老旧工具结果替换为一行摘要
     - 历史裁剪（snip），超出 token 预算时从前面裁剪
  3. LLM 调用超时（asyncio.wait_for）
  4. **并发安全**：所有 per-request 数据通过参数传入，不依赖实例可变状态。
     per-session 历史用 asyncio.Lock 保护，多用户并发安全。
"""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.provider import LLMProvider, LLMResponse, ToolCallRequest
from context.builder import ContextBuilder
from tools.registry import ToolRegistry

MAX_TURN_ITERATIONS = 10
MAX_TOOL_RESULT_CHARS = 3000       # 单个工具结果最大字符数
MICROCOMPACT_KEEP_RECENT = 6       # 保留最近 N 个工具结果的完整内容
LLM_TIMEOUT_S = 120.0              # 单次 LLM 调用超时（秒）
MAX_HISTORY_MESSAGES = 40          # 历史消息最大条数


# ============================================================================
# 返回类型
# ============================================================================

@dataclass
class TurnResult:
    """一轮对话的结果，所有字段 per-request 隔离。"""
    final_content: str | None = None
    stop_reason: str = "completed"
    tools_called: list[str] = field(default_factory=list)


# ============================================================================
# AgentLoop
# ============================================================================

class AgentLoop:
    """Agent 主循环引擎——并发安全。

    关键设计决策（区别于旧版）：
      - 所有 per-request 状态（profile、context）通过 process_direct() 参数传入，
        不通过 setter 修改实例变量，杜绝并发数据泄露。
      - last_tools_called 从 process_direct() 的返回值中获取，而非实例属性。
      - per-session 历史用 asyncio.Lock 保护。
    """

    def __init__(
        self,
        bus,
        provider: LLMProvider,
        workspace_path: str,
        tools: ToolRegistry | None = None,
        session_store=None,  # SessionStore 实例（可选，启用持久化）
    ):
        self.bus = bus
        self.provider = provider
        self.workspace_path = workspace_path
        self.tools = tools or ToolRegistry()
        self._store = session_store  # 持久化层

        # per-session 对话历史缓存（并发安全：每次读写加锁）
        self._histories: dict[str, list[dict[str, Any]]] = {}
        self._history_locks: dict[str, asyncio.Lock] = {}

    # ── 对外接口 ──────────────────────────────────────────────────────

    async def process_direct(
        self,
        content: str,
        session_key: str = "default",
        *,
        profile_text: str = "",
        context_text: str = "",
    ) -> TurnResult:
        """处理一条用户消息，返回 Agent 回复。

        所有 per-request 数据通过参数传入，不修改实例状态。
        多用户并发调用时互不干扰。

        Args:
            content:      用户消息正文
            session_key:  会话标识
            profile_text: 顾客长期画像（进入 system prompt）
            context_text: 当前会话上下文（进入 user message）

        Returns:
            TurnResult —— final_content + stop_reason + tools_called
        """
        # 1. 创建 per-request 的 ContextBuilder（不共享）
        ctx_builder = ContextBuilder(Path(self.workspace_path))
        ctx_builder.set_tools(self.tools)
        ctx_builder.set_profile(profile_text)
        ctx_builder.set_context(context_text)

        # 2. 线程安全地获取历史
        history = await self._get_history(session_key)

        # 3. 构建 messages
        messages = ctx_builder.build_messages(
            user_message=content,
            history=history,
        )

        # 4. 执行 ReAct 循环
        result = await self._run_react_loop(messages)

        # 5. 保存本轮对话到历史
        await self._save_history(session_key, messages, result)

        return result

    # ── ReAct 循环 ────────────────────────────────────────────────────

    async def _run_react_loop(
        self,
        messages: list[dict[str, Any]],
    ) -> TurnResult:
        """执行 ReAct 循环：LLM ⇄ 工具。

        每轮迭代前做上下文治理（借鉴 nanobot）：
          1. 清理孤儿 tool_result
          2. 老旧工具结果 → 一行摘要（microcompact）
          3. 工具结果截断
          4. 历史裁剪（snip）
        """
        tools_called: list[str] = []

        for iteration in range(MAX_TURN_ITERATIONS):
            # ── 上下文治理 ──
            messages = self._govern_context(messages)

            # ── 调 LLM（带超时）──
            print(f"  [turn {iteration + 1}] calling LLM ({len(messages)} msgs)...")
            try:
                response = await asyncio.wait_for(
                    self.provider.chat_with_retry(
                        messages=messages,
                        tools=self.tools.get_definitions() if len(self.tools) > 0 else None,
                    ),
                    timeout=LLM_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                print(f"  [agent] LLM 调用超时（{LLM_TIMEOUT_S}s）")
                return TurnResult(
                    final_content="抱歉，AI 服务响应超时，请稍后重试。",
                    stop_reason="timeout",
                    tools_called=tools_called,
                )

            # ── 错误处理 ──
            if response.finish_reason == "error":
                return TurnResult(
                    final_content=response.content or "抱歉，AI 服务暂时不可用，请稍后重试。",
                    stop_reason="error",
                    tools_called=tools_called,
                )

            # ── 有工具调用 → 执行 → 继续循环 ──
            if response.has_tool_calls:
                tool_names = [tc.name for tc in response.tool_calls]
                print(f"  [agent] calling tools: {', '.join(tool_names)}")
                tools_called.extend(tool_names)

                self._append_assistant_message(messages, response)
                await self._execute_and_append_tools(messages, response.tool_calls)
                continue

            # ── 最终文本回复 ──
            if response.content:
                print(f"  [agent] reply ready ({len(response.content)} chars)")
                return TurnResult(
                    final_content=response.content,
                    stop_reason="completed",
                    tools_called=tools_called,
                )

            # ── 空响应 ──
            return TurnResult(
                final_content="抱歉，我没有生成有效的回复，请换个方式描述你的问题。",
                stop_reason="completed",
                tools_called=tools_called,
            )

        # 超过最大迭代次数
        return TurnResult(
            final_content=f"抱歉，处理你的请求时超出了最大对话轮次（{MAX_TURN_ITERATIONS}），请简化你的问题。",
            stop_reason="max_iterations",
            tools_called=tools_called,
        )

    # ── 上下文治理（借鉴 nanobot AgentRunner）─────────────────────────

    @staticmethod
    def _govern_context(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """每轮 LLM 调用前对 messages 做治理。"""
        msgs = AgentLoop._drop_orphan_tool_results(messages)
        msgs = AgentLoop._microcompact(msgs)
        msgs = AgentLoop._apply_tool_result_budget(msgs)
        msgs = AgentLoop._snip_history(msgs)
        msgs = AgentLoop._drop_orphan_tool_results(msgs)
        return msgs

    @staticmethod
    def _drop_orphan_tool_results(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """删除没有对应 assistant tool_call 的孤儿 tool 消息。"""
        declared: set[str] = set()
        for msg in messages:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls") or []:
                    if isinstance(tc, dict) and tc.get("id"):
                        declared.add(str(tc["id"]))
        return [
            msg for msg in messages
            if msg.get("role") != "tool" or str(msg.get("tool_call_id", "")) in declared
        ]

    @staticmethod
    def _microcompact(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """老旧工具结果 → 一行摘要。保留最近 MICROCOMPACT_KEEP_RECENT 个。"""
        compactable = [
            i for i, msg in enumerate(messages)
            if msg.get("role") == "tool"
        ]
        if len(compactable) <= MICROCOMPACT_KEEP_RECENT:
            return messages

        stale = compactable[:len(compactable) - MICROCOMPACT_KEEP_RECENT]
        for i in stale:
            name = messages[i].get("name", "tool")
            content = messages[i].get("content", "")
            if isinstance(content, str) and len(content) > 200:
                messages[i]["content"] = f"[{name} 结果已压缩——早期轮次，不再展开]"
        return messages

    @staticmethod
    def _apply_tool_result_budget(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """截断过长的工具结果。"""
        for msg in messages:
            if msg.get("role") != "tool":
                continue
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > MAX_TOOL_RESULT_CHARS:
                msg["content"] = (
                    content[:MAX_TOOL_RESULT_CHARS]
                    + f"\n\n... [已截断，完整长度 {len(content)} 字符]"
                )
        return messages

    @staticmethod
    def _snip_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """消息总数超出预算时从前面裁剪，保留 system + 最近 N 条。"""
        if len(messages) <= MAX_HISTORY_MESSAGES:
            return messages

        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        keep_count = max(MAX_HISTORY_MESSAGES - len(system_msgs), 10)
        kept = non_system[-keep_count:]

        # 确保以 user 消息开头
        for i, msg in enumerate(kept):
            if msg.get("role") == "user":
                kept = kept[i:]
                break
        else:
            kept = non_system[-min(len(non_system), 4):]

        return system_msgs + kept

    # ── 工具执行（串行，借鉴 nanobot 的 execute_tools 结构）───────────

    @staticmethod
    def _append_assistant_message(
        messages: list[dict[str, Any]],
        response: LLMResponse,
    ) -> None:
        msg: dict[str, Any] = {
            "role": "assistant",
            "content": response.content or "",
        }
        if response.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": str(tc.arguments)},
                }
                for tc in response.tool_calls
            ]
        messages.append(msg)

    async def _execute_and_append_tools(
        self,
        messages: list[dict[str, Any]],
        tool_calls: list[ToolCallRequest],
    ) -> None:
        """执行工具并追加结果到消息列表。

        借鉴 nanobot 的 _partition_tool_batches：concurrency_safe 的工具并行执行。
        """
        # 检查是否可以并行
        all_safe = all(
            self._is_concurrency_safe(tc.name)
            for tc in tool_calls
        )

        if all_safe and len(tool_calls) > 1:
            # 并行执行
            print(f"  [tool exec] parallel: {', '.join(tc.name for tc in tool_calls)}")
            results = await asyncio.gather(*(
                self._execute_one_tool(tc) for tc in tool_calls
            ))
            for tc, result in zip(tool_calls, results):
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": result,
                })
        else:
            # 串行执行
            for tc in tool_calls:
                print(f"  [tool exec] {tc.name}({tc.arguments})")
                result = await self._execute_one_tool(tc)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": result,
                })

    async def _execute_one_tool(self, tc: ToolCallRequest) -> str:
        """执行单个工具，返回结果字符串。"""
        try:
            result = await self.tools.execute(tc.name, tc.arguments)
        except Exception as exc:
            result = f"工具执行异常: {type(exc).__name__}: {exc}"
            print(f"  [tool error] {tc.name}: {exc}")

        preview = str(result)[:120].replace('\n', ' ')
        if len(str(result)) > 120:
            preview += "..."
        print(f"  [tool result] {tc.name}: {len(str(result))} chars -> {preview}")
        return str(result)

    def _is_concurrency_safe(self, tool_name: str) -> bool:
        """检查工具是否可以并发执行。"""
        tool = self.tools.get(tool_name)
        if tool is None:
            return False
        return getattr(tool, "concurrency_safe", False)

    # ── 历史管理（并发安全）───────────────────────────────────────────

    def _get_lock(self, session_key: str) -> asyncio.Lock:
        """获取 per-session 的锁。"""
        if session_key not in self._history_locks:
            self._history_locks[session_key] = asyncio.Lock()
        return self._history_locks[session_key]

    async def _get_history(self, session_key: str) -> list[dict[str, Any]]:
        """线程安全地读取会话历史（优先从磁盘加载）。"""
        async with self._get_lock(session_key):
            if session_key not in self._histories and self._store is not None:
                # 从磁盘加载
                loaded = await self._store.load_history(session_key)
                if loaded:
                    self._histories[session_key] = loaded
            return list(self._histories.get(session_key, []))

    async def _save_history(
        self,
        session_key: str,
        messages: list[dict[str, Any]],
        result: TurnResult,
    ) -> None:
        """线程安全地保存本轮对话到会话历史（内存 + 磁盘）。"""
        async with self._get_lock(session_key):
            if session_key not in self._histories:
                self._histories[session_key] = []

            history = self._histories[session_key]

            # 找最后一条 user 消息
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    history.append({"role": "user", "content": msg["content"]})
                    break

            # 追加 assistant 回复
            if result.final_content:
                history.append({
                    "role": "assistant",
                    "content": result.final_content,
                })

            # 硬上限
            if len(history) > MAX_HISTORY_MESSAGES:
                self._histories[session_key] = history[-MAX_HISTORY_MESSAGES:]

        # 持久化到磁盘（在锁外执行，避免阻塞其他请求）
        if self._store is not None:
            await self._store.save_history(session_key, self._histories[session_key])

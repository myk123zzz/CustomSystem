"""
LLM Provider 抽象层
====================
借鉴 nanobot/providers/base.py 的设计：
  - LLMProvider 抽象基类，定义统一的 chat() 接口
  - LLMResponse / ToolCallRequest 数据类，标准化输入输出
  - OpenAICompatProvider 封装 OpenAI 兼容接口（DeepSeek、通义千问等）

设计原则（来自 nanobot）：
  1. 上层代码（AgentLoop）完全不感知底层是哪个 LLM 提供商
  2. 换模型只换 Provider，其余代码零改动
  3. 重试、超时、错误处理全部封装在 Provider 内部

简化 vs nanobot：
  - 去掉了 Anthropic 专有格式转换（我们用 OpenAI 兼容）
  - 去掉了 streaming、thinking blocks（第 1 步先用非流式）
  - 重试策略简化为标准 3 次重试
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI


# ============================================================================
# 数据类 —— 借鉴 nanobot/providers/base.py 的 ToolCallRequest / LLMResponse
# ============================================================================

@dataclass
class ToolCallRequest:
    """LLM 返回的工具调用请求。

    借鉴 nanobot 的同名类。一个 LLM 回复可能包含 0-N 个 ToolCall。
    """
    id: str                     # 工具调用唯一 ID（如 "call_abc123"）
    name: str                   # 工具名（如 "faq_lookup"）
    arguments: dict[str, Any]   # 参数（JSON 对象，如 {"query": "退货流程"}）


@dataclass
class LLMResponse:
    """LLM 返回的标准响应。

    借鉴 nanobot 的同名类。统一了文本回复和工具调用两种响应类型。
    """
    content: str | None = None          # 文本回复（纯文本时不为空）
    tool_calls: list[ToolCallRequest] = field(default_factory=list)  # 工具调用列表
    finish_reason: str = "stop"         # "stop" / "tool_calls" / "length" / "error"

    @property
    def has_tool_calls(self) -> bool:
        """是否需要执行工具"""
        return len(self.tool_calls) > 0


# ============================================================================
# 抽象基类 —— 借鉴 nanobot/providers/base.py 的 LLMProvider
# ============================================================================

class LLMProvider(ABC):
    """LLM 提供商抽象基类。

    借鉴 nanobot 的 LLMProvider。所有 LLM 接入都继承此类，
    实现 chat() 方法。上层 AgentLoop 只依赖这个接口。
    """

    def __init__(self, api_key: str, api_base: str, default_model: str):
        self.api_key = api_key
        self.api_base = api_base
        self.default_model = default_model

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        """发送聊天请求，返回统一格式的 LLMResponse。

        Args:
            messages: 消息列表 [{"role": "system/user/assistant", "content": "..."}]
            tools: 工具定义列表（OpenAI function calling 格式），无工具时传 None
            model: 模型名，不传则用 default_model

        Returns:
            LLMResponse（包含文本回复和/或工具调用）
        """
        ...


# ============================================================================
# DeepSeek 实现 —— 借鉴 nanobot/providers/openai_compat_provider.py
# ============================================================================

class DeepSeekProvider(LLMProvider):
    """DeepSeek 提供商（OpenAI 兼容接口）。

    借鉴 nanobot 的 OpenAICompatProvider。DeepSeek 的 API 和 OpenAI 完全兼容，
    直接用 openai 官方 SDK 的 AsyncOpenAI 客户端。

    后续要接其他兼容 OpenAI 接口的模型（通义千问、GLM、Moonshot 等），
    只需改 api_base 和 default_model。
    """

    def __init__(
        self,
        api_key: str,
        api_base: str = "https://api.deepseek.com",
        default_model: str = "deepseek-chat",
    ):
        super().__init__(api_key, api_base, default_model)
        # 使用 OpenAI 官方 SDK 的异步客户端
        # base_url 要拼上 /v1（OpenAI SDK 会自动处理，但明确写出来更安全）
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base.rstrip("/") + "/v1",
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        """调用 DeepSeek API，返回统一格式的 LLMResponse。

        借鉴 nanobot _safe_chat() 的错误处理模式：
        异常不向上抛，而是包装成 finish_reason="error" 的 LLMResponse。
        """
        try:
            # 构建请求参数
            kwargs: dict[str, Any] = {
                "model": model or self.default_model,
                "messages": messages,
            }
            if tools:
                kwargs["tools"] = tools

            # 调用 OpenAI 兼容 API
            completion = await self._client.chat.completions.create(**kwargs)
            choice = completion.choices[0]
            msg = choice.message

            # 解析工具调用
            tool_calls: list[ToolCallRequest] = []
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    # 参数是 JSON 字符串，需要解析
                    import json
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                    tool_calls.append(ToolCallRequest(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    ))

            return LLMResponse(
                content=msg.content or "",
                tool_calls=tool_calls,
                finish_reason=choice.finish_reason or "stop",
            )

        except Exception as exc:
            # 借鉴 nanobot：异常不抛出，包装为错误响应
            return LLMResponse(
                content=f"LLM 调用失败: {exc}",
                finish_reason="error",
            )

    # ---- 重试封装（后续步骤接入）-----------------------------------------
    # 借鉴 nanobot LLMProvider._run_with_retry()
    # 第 1 步先用简单版本，不加重试逻辑

    async def chat_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_retries: int = 3,
    ) -> LLMResponse:
        """带重试的聊天请求（简化版）。

        借鉴 nanobot 的 _run_with_retry。标准模式：最多 3 次重试。
        后续会加入瞬时错误识别、retry-after 解析等。
        """
        import asyncio

        last_response: LLMResponse | None = None
        for attempt in range(1, max_retries + 1):
            response = await self.chat(messages, tools, model)
            if response.finish_reason != "error":
                return response
            last_response = response
            if attempt < max_retries:
                await asyncio.sleep(attempt)  # 退避：1s, 2s, 3s

        return last_response or LLMResponse(
            content="重试耗尽，LLM 调用失败",
            finish_reason="error",
        )

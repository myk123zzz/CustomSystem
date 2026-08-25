"""
ToolRegistry — 工具注册表
===========================
借鉴 nanobot/agent/tools/registry.py 的 ToolRegistry 设计。

核心设计（来自 nanobot）：
  1. 注册/注销工具 → 自动清除定义缓存
  2. get_definitions() 返回 OpenAl function calling 格式，结果缓存
  3. execute() 调工具，出错时附带重试提示

为什么缓存 definitions？
  LLM prompt 里 tools 列表可能占好几 k token。如果每次请求都重新构建
  这个 JSON Schema 列表，浪费 CPU 也浪费 prompt cache 命中率。
  nanobot 的解法是：只在注册/注销工具时重建缓存。
"""

from typing import Any

from .base import Tool


class ToolRegistry:
    """工具注册表。

    借鉴 nanobot 的同名类。Agent 通过它管理所有可用工具。
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._cached_definitions: list[dict[str, Any]] | None = None

    # ---- 注册 / 注销 ----

    def register(self, tool: Tool) -> None:
        """注册一个工具。自动清除定义缓存。"""
        self._tools[tool.name] = tool
        self._cached_definitions = None  # 缓存失效

    def unregister(self, name: str) -> None:
        """注销一个工具。自动清除定义缓存。"""
        self._tools.pop(name, None)
        self._cached_definitions = None

    def get(self, name: str) -> Tool | None:
        """按名称获取工具实例"""
        return self._tools.get(name)

    # ---- 获取定义（给 LLM 看的） ----

    def get_definitions(self) -> list[dict[str, Any]]:
        """获取所有工具的 OpenAI function calling 格式定义。

        借鉴 nanobot 的同名方法。结果被缓存，仅在注册/注销时重建。
        """
        if self._cached_definitions is not None:
            return self._cached_definitions

        definitions = [tool.to_openai_schema() for tool in self._tools.values()]
        self._cached_definitions = definitions
        return definitions

    # ---- 执行工具 ----

    async def execute(self, name: str, params: dict[str, Any]) -> str:
        """执行指定工具。

        借鉴 nanobot 的同名方法。包含参数校验和错误处理。
        出错时会附加重试提示，帮助 LLM 自我纠正。
        """
        tool = self._tools.get(name)
        if tool is None:
            return (
                f"错误: 工具 '{name}' 不存在。"
                f"可用工具: {', '.join(self._tools.keys())}"
            )

        # 参数校验
        errors = tool.validate_params(params)
        if errors:
            return f"参数错误: {'; '.join(errors)}"

        # 执行
        try:
            result = await tool.execute(**params)
            return str(result) if result is not None else "(空结果)"
        except Exception as exc:
            return f"工具执行失败: {type(exc).__name__}: {exc}"

    # ---- 查询 ----

    @property
    def tool_names(self) -> list[str]:
        """所有已注册工具的名称列表"""
        return list(self._tools.keys())

    @property
    def tools(self) -> list[Tool]:
        """所有已注册的工具实例列表（按注册顺序）。"""
        return list(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

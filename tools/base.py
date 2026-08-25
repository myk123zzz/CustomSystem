"""
Tool 抽象基类
==============
借鉴 nanobot/agent/tools/base.py 的 Tool 设计：

核心思想：
  - 每个 Tool 是一个 Agent 可以调用的"能力"
  - name + description 是给 LLM 看的，告诉它这个工具是干嘛的
  - parameters 是 JSON Schema，LLM 按这个格式传参
  - execute() 是真正执行的代码

设计原则（来自 nanobot）：
  1. 工具定义和工具执行完全分离
  2. LLM 看到的只是 name + description + parameters（它不需要知道实现）
  3. 参数校验和类型转换在 execute 之前完成

简化 vs nanobot：
  - 去掉了 cast_params（类型自动转换，后续需要再加）
  - 去掉了 concurrency_safe / exclusive 等并发控制标记
  - Schema 校验简化为基本的 required 检查
"""

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """Agent 工具抽象基类。

    借鉴 nanobot 的 Tool。每个具体工具继承此类，
    实现 name、description、parameters、execute 四个抽象成员。

    用法示例：
        class FAQTool(Tool):
            name = "faq_lookup"
            description = "搜索 FAQ 知识库"
            parameters = {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            }

            async def execute(self, query: str) -> str:
                return "查到了..."
    """

    # ---- 子类必须实现的四个抽象成员 ----

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名。LLM 通过这个名字来调用工具。例如 "faq_lookup"、"order_query" """
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述。告诉 LLM 这个工具是干嘛的、什么时候该用、什么时候不该用。

        这是 prompt engineering 的关键位置——描述写得越好，
        LLM 越知道在什么场景下调用这个工具。
        """
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """参数 JSON Schema。告诉 LLM 调用这个工具需要传什么参数。

        格式遵循 OpenAI function calling 的 parameters 规范：
        {
            "type": "object",
            "properties": {
                "param1": {"type": "string", "description": "..."},
                "param2": {"type": "integer", "description": "..."},
            },
            "required": ["param1"],
        }
        """
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """执行工具，返回结果字符串。

        这是 Agent 真正"干活"的地方——查数据库、调 API、发通知等。
        返回的字符串会作为 tool result 发回给 LLM。
        """
        ...

    # ---- 并发控制（借鉴 nanobot）----

    @property
    def concurrency_safe(self) -> bool:
        """该工具是否可以与其他工具并发执行。

        只读工具（查询、搜索）→ True。
        有副作用的工具（写入、发送通知）→ False。
        默认 True，因为客服场景大多数工具是只读的。
        """
        return True

    # ---- 提供给 ToolRegistry 的方法 ----

    def to_openai_schema(self) -> dict[str, Any]:
        """生成 OpenAI function calling 格式的工具定义。

        借鉴 nanobot Tool.to_schema()。
        LLM 的 tools 参数就是这个格式的列表。
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """校验参数是否符合 JSON Schema。返回错误列表，空列表表示通过。

        借鉴 nanobot Schema.validate_json_schema_value()。
        第 1 步只做基本检查，后续完善。
        """
        errors: list[str] = []
        schema = self.parameters or {}
        required: list[str] = schema.get("required", [])

        for key in required:
            if key not in params:
                errors.append(f"缺少必填参数: {key}")

        return errors

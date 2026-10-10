from typing import Any

import pytest

from tools.base import Tool
from tools.registry import ToolRegistry


class EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Return the supplied text."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    async def execute(self, text: str) -> str:
        return text


@pytest.mark.asyncio
async def test_registry_validates_and_executes_tools():
    registry = ToolRegistry()
    registry.register(EchoTool())

    assert registry.tool_names == ["echo"]
    assert await registry.execute("echo", {}) == "参数错误: 缺少必填参数: text"
    assert await registry.execute("echo", {"text": "hello"}) == "hello"


def test_tool_definition_cache_is_invalidated_on_unregister():
    registry = ToolRegistry()
    registry.register(EchoTool())
    first = registry.get_definitions()

    assert first[0]["function"]["name"] == "echo"

    registry.unregister("echo")

    assert registry.get_definitions() == []


def test_subset_exposes_only_allowed_tools():
    registry = ToolRegistry()
    registry.register(EchoTool())

    subset = registry.subset({"echo"})

    assert subset.tool_names == ["echo"]
    assert subset.get("echo") is registry.get("echo")


def test_subset_rejects_unknown_permissions():
    registry = ToolRegistry()

    with pytest.raises(ValueError, match="未知工具"):
        registry.subset({"missing"})


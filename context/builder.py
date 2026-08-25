"""
ContextBuilder —— 上下文构建器
================================
借鉴 nanobot/agent/context.py 的设计模式。

核心设计：
  System prompt  = AGENTS.md（身份）+ 顾客画像（长期记忆）+ 工具契约
                   → 同一会话内尽量稳定，利于 provider 的 prompt caching

  User message   = [运行时上下文] + 用户原话
                   → 每轮变化的动态信息挂在 user message 上，
                   不污染 system prompt，跟 nanobot 的 Runtime Context 一致

这种分离让 system prompt 前缀保持稳定（provider 可以缓存），
而每轮变化的元数据（当前订单号、会话意图等）附着在 user message 尾部。
"""

from pathlib import Path


class ContextBuilder:
    """拼装发给 LLM 的 messages 列表。

    用法::

        cb = ContextBuilder(workspace)
        cb.set_profile("顾客画像文本")       # → system prompt
        cb.set_context("当前订单: 88001")    # → user message
        cb.set_tools(tool_registry)          # → 动态生成工具说明
        messages = cb.build_messages("用户问题", history=[...])
    """

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md"]
    _CONTEXT_TAG = "[运行时上下文 — 仅供参考，非用户原话]"
    _CONTEXT_END = "[/运行时上下文]"

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self._profile_text: str = ""       # 顾客长期画像 → 进入 system prompt
        self._context_text: str = ""       # 当前会话元数据 → 进入 user message
        self._tool_registry = None         # 工具注册表引用

    # ── 注入接口 ──────────────────────────────────────────────────────

    def set_profile(self, text: str):
        """注入顾客长期画像。

        包含顾客姓名、标签、投诉次数、上次对话摘要等。
        这些信息进入 system prompt，同一顾客的连续对话中保持稳定。
        """
        self._profile_text = text

    def set_context(self, text: str):
        """注入当前会话上下文。

        包含当前处理的订单号、检测到的用户意图、会话状态等。
        这些信息每轮都可能变化，挂在 user message 上而非 system prompt。
        """
        self._context_text = text

    def set_tools(self, registry) -> None:
        """注入工具注册表引用，用于动态生成工具使用说明。

        这样 _tool_contract() 始终与 server.py 中注册的工具保持同步，
        不会出现"注册了 4 个工具但 system prompt 只写了 2 个"的问题。
        """
        self._tool_registry = registry

    # ── system prompt ─────────────────────────────────────────────────

    def build_system_prompt(self) -> str:
        """构建 system prompt：身份 + 画像 + 工具契约。

        system prompt 在同一顾客的连续对话中保持稳定，
        provider 可以利用 prompt caching 减少首 token 延迟。
        """
        parts: list[str] = []

        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        if self._profile_text:
            parts.append(self._profile_text)

        contract = self._tool_contract()
        if contract:
            parts.append(contract)

        return "\n\n---\n\n".join(parts)

    # ── user message ──────────────────────────────────────────────────

    def build_user_message(self, user_text: str) -> str:
        """构建 user message：运行时上下文 + 用户原话。

        类似 nanobot 的 Runtime Context，动态上下文挂在 user message 上。
        system prompt 保持干净，可以享受 provider 的 prompt caching。
        """
        if not self._context_text:
            return user_text
        return (
            f"{self._CONTEXT_TAG}\n"
            f"{self._context_text}\n"
            f"{self._CONTEXT_END}\n\n"
            f"{user_text}"
        )

    # ── messages 列表 ─────────────────────────────────────────────────

    def build_messages(
        self,
        user_message: str,
        history: list[dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        """构建完整 messages 列表：[system, ...history, user]。

        这是发给 LLM 的最终格式。
        """
        return [
            {"role": "system", "content": self.build_system_prompt()},
            *(history or []),
            {"role": "user", "content": self.build_user_message(user_message)},
        ]

    # ── 内部方法 ──────────────────────────────────────────────────────

    def _load_bootstrap_files(self) -> str:
        """加载 workspace 下的引导文件（AGENTS.md 等）。"""
        parts: list[str] = []
        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")
        return "\n\n".join(parts) if parts else ""

    def _tool_contract(self) -> str:
        """动态生成工具使用说明。

        从 ToolRegistry 读取已注册的工具列表，自动生成描述。
        新增工具无需手动更新此处——注册即生效。
        """
        if self._tool_registry is None or len(self._tool_registry) == 0:
            return ""

        lines: list[str] = [
            "## 可用工具",
            "",
            "你可以调用以下函数获取实时数据（禁止凭记忆编造答案）：",
            "",
        ]

        for tool in self._tool_registry.tools:
            lines.append(f"### `{tool.name}`")
            lines.append(f"{tool.description}")
            params = tool.parameters
            if params and params.get("properties"):
                required_fields = params.get("required", [])
                for pname, pinfo in params["properties"].items():
                    req_mark = "（必填）" if pname in required_fields else ""
                    pdesc = pinfo.get("description", "")
                    lines.append(f"  - `{pname}`: {pdesc}{req_mark}")
            lines.append("")

        lines.append("**规则**:")
        lines.append("- 政策咨询（退换/物流/保修/发票）→ 先调 faq_lookup 或 rag_search")
        lines.append("- 订单查询 → 先调 order_query")
        lines.append("- 无法处理的问题 → 调 request_human 转人工")
        lines.append("- 拿到工具结果后自然回复，不要照搬原文")

        return "\n".join(lines)

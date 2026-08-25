"""
安全边界 —— 输入校验 + 工具层防护（借鉴 nanobot/security/）
==============================================================
nanobot 的安全策略：
  - 工具执行前检查 SSRF（防止访问内网 URL）
  - workspace 越界检测（防止读/写工作区外的文件）
  - 重试升级（重复违规→更严格的处理）

我们的客服场景适配：
  - 输入校验：长度限制、注入模式检测
  - SQL 注入防护：由 asyncpg 的参数化查询保证
  - 工具参数校验：ToolRegistry.execute() 已做 required 检查
"""

import re

MAX_MESSAGE_LENGTH = 2000        # 单条消息最大字符数
MAX_SESSION_TURNS = 100          # 单个会话最大轮次


# 明显的 prompt injection 尝试模式
_INJECTION_PATTERNS = [
    r"(?i)ignore\s+(all\s+)?(previous|above|prior)\s+instructions?",
    r"(?i)forget\s+(all\s+)?(your\s+)?(previous\s+)?(instructions?|rules?)",
    r"(?i)you\s+are\s+now\s+(a\s+)?(different|new)\s+(ai|assistant|agent)",
    r"(?i)system\s*prompt\s*(:|=|is|was)",
]


class SecurityError(Exception):
    """安全违规异常。"""


def validate_message(msg: str) -> str:
    """校验用户消息，返回清理后的消息或抛出 SecurityError。

    借鉴 nanobot 的输入层安全逻辑。
    """
    if not msg or not msg.strip():
        raise SecurityError("消息不能为空")

    # 长度限制
    if len(msg) > MAX_MESSAGE_LENGTH:
        raise SecurityError(f"消息过长（最大 {MAX_MESSAGE_LENGTH} 字符）")

    # 注入检测
    for pattern in _INJECTION_PATTERNS:
        if re.search(pattern, msg):
            raise SecurityError("检测到不安全的输入模式，消息已被拒绝")

    # 清理控制字符（保留换行）
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', msg)

    return cleaned.strip()

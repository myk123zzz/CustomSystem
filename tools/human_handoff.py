"""
转人工工具
============
Agent 在不确定时主动调用此工具，将对话转接给人工客服。
"""

from tools.base import Tool


class HumanHandoffTool(Tool):
    """请求人工客服接管当前对话。"""

    @property
    def name(self) -> str:
        return "request_human"

    @property
    def description(self) -> str:
        return (
            "将当前对话转接给人工客服。在以下情况使用：\n"
            "1. 你无法确定答案，多次查询后仍不确定\n"
            "2. 用户明确要求转人工\n"
            "3. 用户投诉或表现出强烈不满\n"
            "4. 问题超出了你的能力范围\n"
            "参数 reason: 转人工的原因（简短说明）"
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "转人工的原因，如'无法确定退款金额'、'用户要求投诉'",
                },
            },
            "required": ["reason"],
        }

    @property
    def concurrency_safe(self) -> bool:
        # 转人工是有副作用的动作（通知人工/建工单），不是只读查询，
        # 不能和其他工具并行执行。覆盖基类默认的 True。
        return False

    async def execute(self, reason: str = "") -> str:
        print(f"     [request_human] 转人工原因: {reason}")
        return (
            "已通知人工客服，请稍等～我们的客服同事会马上接入。\n"
            f"（转接原因: {reason}）"
        )

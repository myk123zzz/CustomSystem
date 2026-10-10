"""
置信度评估器
==============
不看 Agent 说了什么，看 Agent 做了什么。

评估维度（行为驱动，不是文本分析）：
  1. 有没有调工具？        调了 +0.3，没调 -0.2（如果问题需要工具）
  2. 工具返回有效数据了吗？ 有数据 +0.3，空结果 +0.1
  3. 回复里有没有确切信息？ 有订单号/金额/明确政策 +0.2
  4. 错误/异常？           LLM 报错 -0.5

分数范围 0.0-1.0，阈值 0.5 以下标记为"需要人工关注"。
"""

from dataclasses import dataclass, field


@dataclass
class ConfidenceResult:
    """评估结果"""
    score: float                        # 0.0 ~ 1.0
    level: str                          # "high" / "medium" / "low"
    needs_human: bool                   # 是否需要人工介入
    reason: str                         # 评估理由（给人看的）
    summary: str = ""                   # 接管摘要（低置信度时附带）


class ConfidenceEvaluator:
    """行为驱动的置信度评估。

    不分析 Agent 回复文本里的"可能""不确定"等词——这些不可靠。
    只看事实：调工具没？工具成功没？回复里有确切数据没？
    """

    # 需要工具的意图关键词（这些意图下如果 Agent 没调工具，扣分）
    TOOL_REQUIRED_KEYWORDS = [
        "订单", "退货", "退款", "换货", "物流", "快递",
        "保修", "发票", "发货", "支付", "取消",
    ]

    def evaluate(
        self,
        user_message: str,
        agent_reply: str,
        tools_called: list[str] | None = None,
        tool_success: bool = False,
        had_error: bool = False,
    ) -> ConfidenceResult:
        """评估一次 Agent 回复的置信度。

        Args:
            user_message: 用户原始消息
            agent_reply:   Agent 的回复文本
            tools_called:  本轮调用了哪些工具（None 表示没走 Agent，是路由直达）
            tool_success:  工具是否返回了有效数据
            had_error:     LLM 是否报错
        """
        score = 0.5  # 基准分
        reasons: list[str] = []

        # ---- 1. 工具调用情况 ----
        if tools_called is None:
            # 路由直达（FAQ/关键词），天然高置信度
            score += 0.4
            reasons.append("路由直达（非 LLM），置信度天然高")
        elif len(tools_called) == 0:
            # Agent 没调任何工具
            needs_tool = any(kw in user_message for kw in self.TOOL_REQUIRED_KEYWORDS)
            if needs_tool:
                score -= 0.3
                reasons.append("问题需要工具查询但 Agent 未调用任何工具")
            else:
                # 闲聊类问题不需要工具，正常
                reasons.append("闲聊类问题，无需工具")
        else:
            # Agent 调了工具
            score += 0.3
            reasons.append(f"Agent 调用了工具: {', '.join(tools_called)}")

            if tool_success:
                score += 0.2
                reasons.append("工具返回了有效数据")
            else:
                score += 0.0  # 调了但没结果，不加分
                reasons.append("工具未返回有效数据")

        # ---- 2. 错误/异常 ----
        if had_error:
            score -= 0.5
            reasons.append("LLM 调用出错")

        # ---- 3. 确切信息检测（简单关键词） ----
        if any(kw in agent_reply for kw in ["订单号", "Order", "¥", "元", "物流", "已签收", "运输中"]):
            score += 0.1
            reasons.append("回复中包含确切信息（订单号/金额/物流）")

        # ---- 4. 确定等级 ----
        score = max(0.0, min(1.0, score))

        if score >= 0.7:
            level = "high"
            needs_human = False
        elif score >= 0.5:
            level = "medium"
            needs_human = False
        else:
            level = "low"
            needs_human = True

        # 生成接管摘要
        summary = ""
        if needs_human:
            summary = self._build_handoff_summary(
                user_message, agent_reply, tools_called, score, reasons
            )

        return ConfidenceResult(
            score=round(score, 2),
            level=level,
            needs_human=needs_human,
            reason="; ".join(reasons),
            summary=summary,
        )

    def _build_handoff_summary(
        self,
        user_message: str,
        agent_reply: str,
        tools_called: list[str] | None,
        score: float,
        reasons: list[str],
    ) -> str:
        """生成 100 字左右的接管摘要，供人工客服快速了解上下文。"""
        tools_info = ", ".join(tools_called) if tools_called else "无"
        reply_preview = agent_reply[:80].replace("\n", " ")
        return (
            f"[低置信度告警] 评分: {score}\n"
            f"  用户问题: {user_message[:80]}\n"
            f"  Agent 工具: {tools_info}\n"
            f"  Agent 回复: {reply_preview}...\n"
            f"  原因: {'; '.join(reasons)}"
        )

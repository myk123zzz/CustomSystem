"""
订单查询工具
==============
Agent 调用此工具根据订单号或手机号查询订单。

设计原则（和 FaqLookupTool 一样）：
  - 工具描述告诉 LLM 什么时候该调、传什么参数
  - SQL 查询逻辑封装在 execute() 内部，LLM 看不到
  - 权限校验（后续加）：只返回和当前用户身份匹配的订单
"""

from sqlalchemy import select

from db.connection import get_session
from db.models import Order
from tools.base import Tool


class OrderQueryTool(Tool):
    """查询订单状态和物流信息。"""

    @property
    def name(self) -> str:
        return "order_query"

    @property
    def description(self) -> str:
        return (
            "查询顾客的订单信息。根据订单号或手机号后四位查询。\n"
            "参数说明：\n"
            "  - order_id: 订单号（5 位数字，如 '88001'）\n"
            "  - phone_last4: 手机号后四位（如 '5678'），用于验证身份和查找该用户的所有订单\n"
            "至少需要提供 order_id 或 phone_last4 其中一个。\n"
            "返回订单详情（商品、价格、日期、物流状态）。"
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "订单号（5 位数字）",
                },
                "phone_last4": {
                    "type": "string",
                    "description": "顾客手机号后四位",
                },
            },
            "required": [],
        }

    async def execute(
        self,
        order_id: str | None = None,
        phone_last4: str | None = None,
    ) -> str:
        async with get_session() as session:
            print(f"     [order_query] 查询条件: 订单号={order_id}, 手机号后四位={phone_last4}")
            rows = []

            if order_id:
                stmt = select(Order).where(Order.id == str(order_id))
                result = await session.execute(stmt)
                rows = result.scalars().all()

            elif phone_last4:
                # 用 LIKE 模糊匹配手机号后四位
                stmt = select(Order).where(Order.phone.ilike(f"%{phone_last4}"))
                result = await session.execute(stmt)
                rows = result.scalars().all()

            else:
                return "查询订单需要提供订单号或手机号后四位，请向顾客询问。"

            print(f"     [order_query] 查到 {len(rows)} 条订单")
            if not rows:
                print(f"     [order_query] 未找到匹配订单")
                return "未找到匹配的订单。请确认订单号或手机号是否正确。"

            lines = ["查询到以下订单：\n"]
            for o in rows:
                lines.append(
                    f"Order #{o.id}\n"
                    f"   商品: {o.product_name} × {o.quantity}  |  ¥{o.price}\n"
                    f"   下单日期: {o.order_date}  |  状态: {o.status}\n"
                    f"   物流: {o.logistics}\n"
                )
            return "\n".join(lines)

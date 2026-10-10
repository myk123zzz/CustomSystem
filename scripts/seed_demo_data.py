"""Insert idempotent Multi-Agent demonstration records into PostgreSQL."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from sqlalchemy import func, select

load_dotenv(ROOT / ".env")

from db.connection import get_session, init_db
from db.models import CustomerProfile, Faq, Order, Product


PRODUCTS = [
    Product(
        id="DEMO-P01", name="差旅全能快充套装 100W", price=239, stock=66,
        category="充电套装",
        description="100W 三口氮化镓充电器、100W C to C 线和多国转换插头；适合经常出差、同时携带笔记本与手机的用户。",
    ),
    Product(
        id="DEMO-P02", name="Qi2 超薄磁吸充电宝 5000mAh", price=149, stock=120,
        category="充电宝",
        description="通过 Qi2 标准，15W 磁吸无线充电，厚 8.9mm、重 118g；适合通勤和轻装出行。",
    ),
    Product(
        id="DEMO-P03", name="电竞桌面充电扩展坞 140W", price=329, stock=18,
        category="充电器",
        description="2C2A 四口 140W 输出，带 HDMI 4K、千兆网口和功率数显；适合游戏本与桌面多设备场景。",
    ),
    Product(
        id="DEMO-P04", name="户外防水充电宝 30000mAh", price=269, stock=32,
        category="充电宝",
        description="IP67 防尘防水，带照明和 SOS 模式，支持 65W 双向快充；适合露营、徒步和应急供电。",
    ),
    Product(
        id="DEMO-P05", name="Qi2 折叠三合一旅行充电器", price=299, stock=45,
        category="充电器",
        description="同时为手机、手表和耳机充电，支持 Qi2 15W，折叠后掌心大小，附旅行收纳盒。",
    ),
    Product(
        id="DEMO-P06", name="迷你双口充电头 45W", price=69, stock=210,
        category="充电器",
        description="1C1A 双口，单口最高 45W，双口智能分配；适合手机和平板日常通勤。",
    ),
    Product(
        id="DEMO-P07", name="USB4 全功能数据线 240W", price=99, stock=140,
        category="数据线",
        description="支持 240W PD3.1、40Gbps 数据和 8K 视频输出，适配高性能笔记本与扩展坞。",
    ),
    Product(
        id="DEMO-P08", name="功率数显氮化镓充电器 100W", price=189, stock=74,
        category="充电器",
        description="彩屏实时显示各端口功率与温度，2C1A 三口输出，适合关注充电状态的数码用户。",
    ),
    Product(
        id="DEMO-P09", name="儿童安全智能插线板 65W", price=129, stock=88,
        category="配件",
        description="新国标安全门、过载断电、阻燃外壳，支持 App 定时和 65W USB-C 快充，适合家庭书桌。",
    ),
    Product(
        id="DEMO-P10", name="车载双口快充器 80W", price=79, stock=190,
        category="车载配件",
        description="USB-C 60W 加 USB-A 20W，支持 12V/24V 车型，可同时为笔记本和手机充电。",
    ),
    Product(
        id="DEMO-P11", name="骨传导运动耳机 Air", price=259, stock=57,
        category="耳机",
        description="开放双耳设计，IP68 防水，内置 32GB 存储，适合游泳、跑步和骑行。",
    ),
]

ORDERS = [
    Order(
        id="88901", phone="151****1024", product_name="差旅全能快充套装 100W",
        price=239, quantity=1, order_date="2026-08-24", status="待发货",
        logistics="仓库已拣货，预计 2026-08-27 18:00 前发出",
    ),
    Order(
        id="88902", phone="151****1024", product_name="Qi2 超薄磁吸充电宝 5000mAh",
        price=149, quantity=1, order_date="2026-08-22", status="运输中",
        logistics="顺丰 SF20260826001 — 2026-08-26 15:40 到达【杭州滨江中转场】",
    ),
    Order(
        id="88903", phone="186****7788", product_name="电竞桌面充电扩展坞 140W",
        price=329, quantity=1, order_date="2026-08-18", status="已签收",
        logistics="京东 JD20260821001 — 2026-08-21 11:20 已签收；客户反馈 HDMI 接口无信号，待售后核验",
    ),
    Order(
        id="88904", phone="186****7788", product_name="蓝牙降噪耳机 Pro",
        price=299, quantity=1, order_date="2026-08-10", status="退款中",
        logistics="退货件已于 2026-08-25 入库，预计 1-3 个工作日原路退款",
    ),
    Order(
        id="88905", phone="139****2048", product_name="户外防水充电宝 30000mAh",
        price=269, quantity=1, order_date="2026-08-20", status="运输中",
        logistics="中通 7520260826001 — 2026-08-26 18:20 离开【成都分拨中心】",
    ),
    Order(
        id="88906", phone="139****2048", product_name="USB4 全功能数据线 240W",
        price=99, quantity=2, order_date="2026-08-16", status="已签收",
        logistics="顺丰 SF20260819006 — 2026-08-19 10:06 已签收",
    ),
    Order(
        id="88907", phone="158****3306", product_name="Qi2 折叠三合一旅行充电器",
        price=299, quantity=1, order_date="2026-08-25", status="待发货",
        logistics="订单已支付，仓库配货中，预计 24 小时内发出",
    ),
    Order(
        id="88908", phone="158****3306", product_name="骨传导运动耳机 Air",
        price=259, quantity=1, order_date="2026-08-12", status="售后处理中",
        logistics="客户反馈游泳后无法开机，已登记质量检测",
    ),
]

FAQS = [
    Faq(
        question="Qi2 磁吸充电宝兼容哪些手机？",
        answer="支持 Qi2 的手机可直接实现最高 15W 磁吸无线充电；其他支持无线充电的机型需搭配磁吸壳或磁吸环，实际功率以手机协议为准。",
        category="商品",
    ),
    Faq(
        question="多件设备一起充电会降功率吗？",
        answer="会按端口协议动态分配总功率。连接多台设备时单口功率可能下降；笔记本建议接标有 100W/140W 的主 USB-C 口。",
        category="商品",
    ),
    Faq(
        question="售后核验需要提供什么？",
        answer="请提供订单号、故障现象，以及能展示问题的照片或短视频。涉及序列号的商品还需拍摄机身标签；核验通过后客服会给出换新或退款方案。",
        category="售后",
    ),
    Faq(
        question="充电器多个端口的功率怎么分配？",
        answer="多口同时使用时会根据设备协议动态分配。笔记本应优先连接标注 C1 或 Laptop 的主口，具体组合功率以商品详情页表格为准。",
        category="商品",
    ),
    Faq(
        question="充电宝长期不用怎么保存？",
        answer="建议保留约 50% 电量，放在阴凉干燥处，每 3 个月补充一次电；不要长期满电、亏电或放在高温车内。",
        category="商品",
    ),
    Faq(
        question="防水产品进水后还能保修吗？",
        answer="防水等级只适用于实验室条件，液体损坏通常不属于标准保修。请立即停止使用并联系售后检测，切勿自行充电或烘干。",
        category="售后",
    ),
    Faq(
        question="USB4 数据线和普通快充线有什么区别？",
        answer="USB4 全功能线除充电外还支持 40Gbps 高速数据和视频输出；普通快充线通常只有 480Mbps 数据能力，也可能不支持视频。",
        category="商品",
    ),
    Faq(
        question="磁吸充电时手机发热正常吗？",
        answer="轻微温热属于正常现象。若明显烫手，请取下厚手机壳、停止边充边玩，并检查是否有异物；持续高温应停止使用并联系售后。",
        category="商品",
    ),
    Faq(
        question="户外充电宝能不能带上飞机？",
        answer="需查看机身 Wh 标识。额定能量不超过 100Wh 通常可随身携带；30000mAh 产品可能超过 100Wh，登机前应向航空公司确认，且不可托运。",
        category="商品",
    ),
    Faq(
        question="订单显示签收但本人没收到怎么办？",
        answer="请先检查驿站、门卫和家人代收情况；仍未找到时提供订单号，客服会联系快递核实签收底单并发起异常件调查。",
        category="物流",
    ),
    Faq(
        question="同一订单可以拆分开发票吗？",
        answer="同一订单默认按实际支付金额开一张发票。如需按商品拆分，请在发货前联系人工客服登记，开票后通常无法重新拆分。",
        category="支付",
    ),
]

PROFILES = [
    CustomerProfile(
        phone="151****1024", name="林先生", complaint_count=0, refund_count=0,
        total_orders=5, vip_level="gold", preferred_category="充电器",
        avg_order_amount=188, last_intent="logistics",
        last_summary="经常出差，关注轻便、笔记本快充和发货时效。",
        last_session_time="2026-08-26 20:30", tags="business_travel,fast_charge",
    ),
    CustomerProfile(
        phone="186****7788", name="周女士", complaint_count=1, refund_count=1,
        total_orders=3, vip_level="silver", preferred_category="数码配件",
        avg_order_amount=276, last_intent="after_sales",
        last_summary="扩展坞 HDMI 无信号，正在收集售后核验材料。",
        last_session_time="2026-08-26 19:10", tags="after_sales_active,quality_sensitive",
    ),
]


async def main() -> None:
    await init_db()
    async with get_session() as session:
        for row in PRODUCTS + ORDERS + PROFILES:
            await session.merge(row)

        for faq in FAQS:
            existing = await session.scalar(
                select(Faq).where(Faq.question == faq.question)
            )
            if existing:
                existing.answer = faq.answer
                existing.category = faq.category
            else:
                session.add(faq)
        await session.commit()

        counts = {}
        for model in (Product, Order, Faq, CustomerProfile):
            counts[model.__tablename__] = await session.scalar(
                select(func.count()).select_from(model)
            )

    print("Demo data upserted successfully:")
    for table, count in counts.items():
        print(f"  {table}: {count}")
    print("Demo order IDs: 88901-88908")


if __name__ == "__main__":
    asyncio.run(main())

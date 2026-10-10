"""
数据库模型
============
SQLAlchemy ORM 模型，对应 PostgreSQL 中的三张表：
  - faq     : 常见问题
  - product : 商品信息
  - "order" : 订单（order 是 SQL 关键字，映射为 customer_order）
"""

from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""
    pass


class Faq(Base):
    """FAQ 常见问题表"""
    __tablename__ = "faq"

    id = Column(Integer, primary_key=True, autoincrement=True)
    question = Column(String(500), nullable=False, comment="问题")
    answer = Column(Text, nullable=False, comment="答案")
    category = Column(String(50), comment="分类（物流/售后/支付/订单/商品）")


class Product(Base):
    """商品表"""
    __tablename__ = "product"

    id = Column(String(20), primary_key=True, comment="商品编号，如 P001")
    name = Column(String(200), nullable=False, comment="商品名称")
    price = Column(Float, nullable=False, comment="价格（元）")
    stock = Column(Integer, default=0, comment="库存数量")
    category = Column(String(50), comment="分类")
    description = Column(Text, comment="商品描述")


class Order(Base):
    """订单表。表名用 customer_order 避免和 SQL 关键字 order 冲突。"""
    __tablename__ = "customer_order"

    id = Column(String(20), primary_key=True, comment="订单号，如 88001")
    phone = Column(String(20), nullable=False, comment="顾客手机号（脱敏）")
    product_name = Column(String(200), comment="商品名称")
    price = Column(Float, comment="单价")
    quantity = Column(Integer, default=1, comment="数量")
    order_date = Column(String(20), comment="下单日期")
    status = Column(String(20), comment="状态：待发货/运输中/已签收")
    logistics = Column(Text, comment="物流信息")


class CustomerProfile(Base):
    """顾客长期画像——结构化字段，供 Router 和 Agent 直接使用。"""
    __tablename__ = "customer_profile"

    phone = Column(String(20), primary_key=True, comment="手机号（脱敏），唯一标识")
    name = Column(String(50), comment="顾客称呼")

    # ── 统计字段（每次对话自动更新）──
    complaint_count = Column(Integer, default=0, comment="历史投诉次数")
    refund_count = Column(Integer, default=0, comment="历史退款次数")
    total_orders = Column(Integer, default=0, comment="累计订单数")

    # ── 偏好字段（从对话中提取）──
    vip_level = Column(String(20), default="normal", comment="VIP等级: normal/silver/gold/platinum")
    preferred_category = Column(String(50), comment="偏好品类")
    avg_order_amount = Column(Float, comment="平均客单价")

    # ── 最近会话 ──
    last_intent = Column(String(30), comment="最近一次意图")
    last_summary = Column(Text, comment="最近对话摘要")
    last_session_time = Column(String(30), comment="最近会话时间")

    # ── 标签（可多选）──
    tags = Column(String(200), comment="标签，逗号分隔，如 vip,high_net_worth,refund_sensitive")

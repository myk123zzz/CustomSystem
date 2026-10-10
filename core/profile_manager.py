"""
顾客长期画像管理（v2 — 结构化字段）
=====================================
跨会话持久化的用户信息，存 PostgreSQL。

v2 改进：
  - 从"文本摘要"升级为"结构化字段"（vip_level / complaint_count / preferred_category ...）
  - Router 可以直接读取画像做决策（投诉次数高的用户直接转人工等）
  - Agent 拿到的不再是一段话，而是结构化的顾客档案

字段设计：
  基础: phone, name
  统计: complaint_count, refund_count, total_orders
  偏好: vip_level, preferred_category, avg_order_amount
  最近: last_intent, last_summary, last_session_time
  标签: tags（vip, high_net_worth, refund_sensitive, frequent_complainer ...）
"""

from datetime import datetime

from sqlalchemy import select

from db.connection import get_session
from db.models import CustomerProfile


class ProfileManager:
    """管理顾客长期画像的读写。"""

    # ── 读取 ──────────────────────────────────────────────────────────

    @staticmethod
    async def resolve_key(phone_hint: str | None) -> str | None:
        """Resolve a last-four hint to an existing canonical profile key."""
        if not phone_hint or not phone_hint.startswith("***"):
            return phone_hint
        tail = phone_hint[-4:]
        async with get_session() as session:
            result = await session.execute(
                select(CustomerProfile.phone).where(
                    CustomerProfile.phone.like(f"%{tail}")
                )
            )
            matches = list(result.scalars().all())
        return matches[0] if len(matches) == 1 else phone_hint

    @staticmethod
    async def get_or_create(phone: str) -> CustomerProfile:
        """根据手机号获取画像。不存在则创建空画像。"""
        async with get_session() as session:
            stmt = select(CustomerProfile).where(CustomerProfile.phone == phone)
            result = await session.execute(stmt)
            profile = result.scalar_one_or_none()

            if profile is None:
                profile = CustomerProfile(phone=phone)
                session.add(profile)
                await session.commit()
                print(f"  [画像] 新顾客: {phone}")

            return profile

    # ── 写入 ──────────────────────────────────────────────────────────

    @staticmethod
    async def update(phone: str, **kwargs):
        """更新画像字段（通用方法）。"""
        async with get_session() as session:
            stmt = select(CustomerProfile).where(CustomerProfile.phone == phone)
            result = await session.execute(stmt)
            profile = result.scalar_one_or_none()

            if profile is None:
                profile = CustomerProfile(phone=phone)
                session.add(profile)

            for key, value in kwargs.items():
                if hasattr(profile, key):
                    setattr(profile, key, value)

            await session.commit()

    @staticmethod
    async def increment(phone: str, field: str, delta: int = 1):
        """自增某个统计字段（complaint_count / refund_count / total_orders）。"""
        async with get_session() as session:
            stmt = select(CustomerProfile).where(CustomerProfile.phone == phone)
            result = await session.execute(stmt)
            profile = result.scalar_one_or_none()

            if profile is None:
                profile = CustomerProfile(phone=phone)
                session.add(profile)

            current = getattr(profile, field, 0) or 0
            setattr(profile, field, current + delta)
            await session.commit()

    # ── 业务方法 ──────────────────────────────────────────────────────

    @staticmethod
    async def note_complaint(phone: str):
        """记录投诉：自增 complaint_count + 打标签。"""
        await ProfileManager.increment(phone, "complaint_count")
        # 投诉 ≥ 3 次 → 标记为 frequent_complainer
        profile = await ProfileManager.get_or_create(phone)
        if profile.complaint_count >= 3:
            await ProfileManager._add_tag(phone, "frequent_complainer")

    @staticmethod
    async def note_refund(phone: str):
        """记录退款：自增 refund_count。"""
        await ProfileManager.increment(phone, "refund_count")

    @staticmethod
    async def note_order(phone: str):
        """记录下单：自增 total_orders。"""
        await ProfileManager.increment(phone, "total_orders")

    @staticmethod
    async def summarize_conversation(phone: str, summary: str, intent: str = ""):
        """更新最近会话摘要 + 意图 + 时间。"""
        await ProfileManager.update(
            phone,
            last_summary=summary[:500],
            last_intent=intent,
            last_session_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )

    @staticmethod
    async def touch_interaction(phone: str, intent: str) -> None:
        """Record the latest customer activity without inventing preferences."""
        await ProfileManager.update(
            phone,
            last_intent=intent,
            last_session_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )

    @staticmethod
    async def _add_tag(phone: str, tag: str):
        """追加标签（去重）。"""
        profile = await ProfileManager.get_or_create(phone)
        existing = set(t.strip() for t in (profile.tags or "").split(",") if t.strip())
        existing.add(tag)
        await ProfileManager.update(phone, tags=",".join(sorted(existing)))

    # ── Router 可用的判断方法 ─────────────────────────────────────────

    @staticmethod
    def is_vip(profile: CustomerProfile | None) -> bool:
        """是否 VIP 用户。"""
        if profile is None:
            return False
        return profile.vip_level in ("gold", "platinum")

    @staticmethod
    def is_high_risk(profile: CustomerProfile | None) -> bool:
        """是否高风险用户（投诉 ≥ 3 次）。"""
        if profile is None:
            return False
        return (profile.complaint_count or 0) >= 3

    # ── System Prompt 注入 ────────────────────────────────────────────

    @staticmethod
    def to_prompt_text(profile: CustomerProfile | None) -> str:
        """把结构化画像转成 Agent 可读的文本，注入 system prompt。

        格式简洁，字段有序，Agent 一眼能抓住重点。
        """
        if profile is None:
            return ""

        lines: list[str] = ["## 当前顾客档案", ""]

        # 身份
        identity = []
        if profile.name:
            identity.append(profile.name)
        if profile.vip_level and profile.vip_level != "normal":
            identity.append(f"VIP: {profile.vip_level}")
        if identity:
            lines.append(f"**顾客**: {' | '.join(identity)}")

        # 关键数字
        stats = []
        if profile.total_orders:
            stats.append(f"累计订单 {profile.total_orders} 单")
        if profile.complaint_count:
            stats.append(f"投诉 {profile.complaint_count} 次")
        if profile.refund_count:
            stats.append(f"退款 {profile.refund_count} 次")
        if stats:
            lines.append(f"**数据**: {'，'.join(stats)}")

        # 偏好
        if profile.preferred_category:
            lines.append(f"**偏好品类**: {profile.preferred_category}")

        # 最近
        if profile.last_intent:
            lines.append(f"**最近意图**: {profile.last_intent}")
        if profile.last_summary:
            lines.append(f"**最近摘要**: {profile.last_summary[:200]}")

        # 标签
        if profile.tags:
            tags = [t.strip() for t in profile.tags.split(",") if t.strip()]
            lines.append(f"**标签**: {', '.join(tags)}")

        # 高风险提醒
        if ProfileManager.is_high_risk(profile):
            lines.append("\n⚠️ 该顾客历史投诉 ≥ 3 次，请特别耐心，优先解决其问题。")

        return "\n".join(lines)

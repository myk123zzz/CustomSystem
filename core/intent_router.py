"""
IntentRouter — 意图分类 + 流量分发
=====================================
v2 设计：不是"逐层尝试"，而是"分类后直达"。

旧流程（v1）：
  用户 → 关键词？→ FAQ？→ RAG？→ Agent（逐层 fallthrough，碰运气）

新流程（v2）：
  用户 → Layer1 正则 → Layer2 关键词 → Layer3 LLM分类 → 直达对应管线
         ↑ 0 token        ↑ 0 token       ↑ ~50 token    ↑ 一步到位

7 条处理管线：
  greeting     — 寒暄 → 模板回复
  faq          — 政策咨询 → faq_lookup 工具 → 结构化回复
  product      — 商品咨询 → rag_search → 匹配结果
  order_query  — 查订单 → order_query 工具 → 结构化回复
  logistics    — 查物流 → order_query(lookup_type=logistics) → 结构化回复
  after_sales  — 售后申请 → 校验订单号 → FAQ + Agent 联合
  complaint    — 投诉 → 标记优先级 → 人工兜底
  complex      — 复杂问题 → Agent 完整 ReAct（唯一走 LLM 对话的管线）

每条管线知道自己需要什么数据、调什么工具、怎么回复。
Agent 从"核心处理器"降级为"最后一条兜底管线"。
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Intent(str, Enum):
    GREETING = "greeting"
    FAQ = "faq"
    PRODUCT = "product"
    ORDER_QUERY = "order_query"
    LOGISTICS = "logistics"
    AFTER_SALES = "after_sales"
    COMPLAINT = "complaint"
    COMPLEX = "complex"


@dataclass
class RouteResult:
    """路由结果——比 v1 多了 intent 和 entities，方便指标统计。"""
    handled: bool = False
    intent: Intent = Intent.COMPLEX
    reply: str | None = None
    entities: dict[str, str] = field(default_factory=dict)  # {order_id, product, ...}
    needs_agent: bool = False  # True = 管线处理了但仍需 Agent 后续


# ============================================================================
# Layer 1: 正则匹配（0 token，100% 精确）
# ============================================================================

# 纯数字 → 订单查询或物流
_RE_ORDER_ID = re.compile(r'(?<!\d)(\d{5})(?!\d)')  # 5 位数字 = 订单号（数字边界，允许紧挨中文）
_RE_TRACKING = re.compile(r'(?<![A-Za-z])(SF|YT|JD|EMS)\d{8,}(?!\d)')  # 快递单号
_RE_PHONE_TAIL = re.compile(r'(\d{4})\s*$')         # 消息末尾 4 位数字 = 手机尾号

GREETINGS = {"你好", "在吗", "有人在吗", "嗨", "hello", "hi", "谢谢", "再见", "拜拜", "好的", "ok"}

# ============================================================================
# Layer 2: 关键词 → 意图（0 token）
# ============================================================================

# 每条规则: (关键词列表, 意图, 额外条件)
# 按优先级排列——越具体的越靠前

INTENT_RULES: list[tuple[list[str], Intent, str | None]] = [
    # ── 投诉（优先级最高，避免被"退货"误匹配）──
    (["投诉", "差评", "举报", "老板", "负责人", "上级"], Intent.COMPLAINT, None),

    # ── 售后办事（"我要退" vs "怎么退"，前者是办事后者是政策）──
    (["我要退", "帮我退", "申请退", "想退", "我要退款", "退钱", "帮我退款",
      "我要换", "帮我换", "想换", "售后", "坏了", "质量问题"], Intent.AFTER_SALES, None),

    # ── 物流查询 ──
    (["物流", "快递", "到哪了", "发货了吗", "什么时候到", "几天能到",
      "送货", "还没到", "没收到"], Intent.LOGISTICS, None),

    # ── 政策 FAQ（"怎么退"、"能退吗"、"退货政策"）──
    (["退货政策", "退货规则", "退货流程", "怎么退货", "如何退货", "能退货吗",
      "退款政策", "怎么退款", "能退款吗", "换货政策", "怎么换货", "能换货吗",
      "保修", "质保", "保修多久", "发票", "开发票",
      "包邮", "运费", "邮费", "快递费", "支付方式", "怎么付款",
      "取消订单", "怎么取消", "能取消吗", "正品", "真货",
      "改地址", "修改地址", "能改地址"], Intent.FAQ, None),

    # ── 商品咨询 ──
    (["多少钱", "价格", "便宜", "贵吗", "规格", "参数", "配置",
      "颜色", "有什么", "哪个好", "推荐", "对比", "有没有"], Intent.PRODUCT, None),

    # ── 订单查询 ──
    (["订单", "查一下", "帮我查", "查查", "看一下", "帮我看看"], Intent.ORDER_QUERY, None),
]


def _classify_layer_1_2(msg: str) -> tuple[Intent, dict[str, str]]:
    """Layer 1 + Layer 2 分类。返回 (意图, 提取的实体)。

    识别不了时返回 (COMPLEX, {})，让 Layer 3 LLM 分类。
    """
    entities: dict[str, str] = {}

    # ── Layer 1: 提取实体 ──
    order_match = _RE_ORDER_ID.search(msg)
    if order_match:
        entities["order_id"] = order_match.group(1)

    tracking_match = _RE_TRACKING.search(msg)
    if tracking_match:
        entities["tracking_no"] = tracking_match.group(0)

    phone_match = _RE_PHONE_TAIL.search(msg)
    if phone_match:
        entities["phone_tail"] = phone_match.group(1)

    # ── 寒暄 ──
    if len(msg) <= 10 and any(g in msg for g in GREETINGS):
        return Intent.GREETING, entities

    # ── 纯订单号（消息几乎只有数字）──
    if entities.get("order_id") and len(msg.replace(" ", "")) <= 6:
        return Intent.ORDER_QUERY, entities

    # ── 只有快递单号 ──
    if entities.get("tracking_no") and len(msg.replace(" ", "")) <= 20:
        return Intent.LOGISTICS, entities

    # ── Layer 2: 关键词匹配 ──
    for keywords, intent, _condition in INTENT_RULES:
        if any(kw in msg for kw in keywords):
            return intent, entities

    # ── 都没命中 → Layer 3 ──
    return Intent.COMPLEX, entities


# ============================================================================
# Layer 3: LLM 分类（~50 token，轻量级）
# ============================================================================

CLASSIFY_PROMPT = """将用户消息分类为以下意图（只输出标签，不解释）：

标签: faq | product | order_query | logistics | after_sales | complaint | complex | greeting

消息: {message}
标签:"""


# ============================================================================
# 处理管线
# ============================================================================

GREETING_REPLY = "你好呀～我是速充科技客服小闪！有什么可以帮你的？"

ACTION_PROMPTS = {
    "退货": "好的～要帮你处理退货。请提供你的**订单号**（5位数字），我帮你查一下订单信息～",
    "退款": "好的～帮你查退款进度。请提供你的**订单号**（5位数字）～",
    "换货": "好的～帮你处理换货。请提供你的**订单号**（5位数字），我帮你查一下是否符合换货条件～",
}


class IntentRouter:
    """意图分类 + 流量分发——Agent 的"前台调度"。

    不再逐层尝试，而是先分类再直达对应管线。
    """

    def __init__(self, tools, kb=None, provider=None, session_factory=None):
        """
        Args:
            tools:           ToolRegistry 实例
            kb:              KnowledgeBase 实例（RAG）
            provider:        LLMProvider 实例（Layer 3 分类用，可选）
            session_factory: callable(session_key) → SessionContext
        """
        self.tools = tools
        self.kb = kb
        self.provider = provider
        self._get_session = session_factory

        # 按意图维度的统计（用于指标面板）
        self._stats: dict[str, int] = {
            "greeting": 0, "faq": 0, "product": 0,
            "order_query": 0, "logistics": 0, "after_sales": 0,
            "complaint": 0, "complex": 0,
            "llm_classify": 0,
        }
        # 响应时间（毫秒），按意图统计
        self._latency: dict[str, list[float]] = {
            k: [] for k in self._stats
        }
        self._handoffs: int = 0  # 转人工次数

    # ── 主入口 ────────────────────────────────────────────────────────

    async def route(self, message: str, session_key: str = "") -> RouteResult:
        """分类 + 分发。返回 RouteResult（handled=True 时无需 Agent）。"""
        msg = message.strip()

        # ---- 0. 会话阶段检查（Agent 在等用户回复 → 跳过路由）----
        if self._get_session and session_key:
            sc = self._get_session(session_key)
            if sc.should_skip_router():
                print(f"  [路由] Agent 等待中（{sc.waiting_for}），跳过分类 → 直达 Agent")
                self._stats["complex"] += 1
                return RouteResult(
                    handled=False, intent=Intent.COMPLEX,
                    needs_agent=True,
                )

        # ---- Layer 1+2: 规则分类（0 token）----
        intent, entities = _classify_layer_1_2(msg)

        # ---- Layer 3: LLM 分类（仅当规则未命中）----
        if intent == Intent.COMPLEX and self.provider is not None:
            intent = await self._llm_classify(msg)
            if intent != Intent.COMPLEX:
                self._stats["llm_classify"] += 1

        self._stats[intent.value] += 1

        # ---- 分发到对应管线 ----
        handler = getattr(self, f"_handle_{intent.value}", self._handle_complex)
        return await handler(msg, entities, session_key)

    # ── 管线: greeting ────────────────────────────────────────────────

    async def _handle_greeting(self, msg: str, entities: dict, sk: str) -> RouteResult:
        print(f"  [路由 → greeting] 模板回复（0 token）")
        return RouteResult(handled=True, intent=Intent.GREETING, reply=GREETING_REPLY)

    # ── 管线: faq ─────────────────────────────────────────────────────

    async def _handle_faq(self, msg: str, entities: dict, sk: str) -> RouteResult:
        """FAQ 管线：SQL ILIKE → RAG 语义搜索 → Agent 三级降级。

        SQL 精确匹配优先（0 token），不命中时降级到 RAG 向量语义搜索（0 LLM token），
        都不行才交 Agent 兜底。用户永远不会看到"FAQ 知识库中没有找到相关信息"这种废话。
        """
        print(f"  [路由 → faq] 查 FAQ 知识库")
        try:
            result = await self.tools.execute("faq_lookup", {"query": msg})
        except Exception as exc:
            print(f"  [路由 → faq] 失败: {exc}")
            return RouteResult(handled=False, intent=Intent.FAQ, needs_agent=True)

        # SQL ILIKE 命中 → 直接返回
        no_hit = "没有找到相关信息" in result
        if not no_hit:
            return RouteResult(handled=True, intent=Intent.FAQ, reply=result)

        # SQL 没命中 → 降级到 RAG 向量语义搜索
        print(f"  [路由 → faq] SQL 未命中，降级到 RAG 语义搜索")
        rag_hit = await self._rag_fallback(msg)
        if rag_hit:
            return rag_hit

        # RAG 也没命中 → 交给 Agent 兜底
        print(f"  [路由 → faq] RAG 也未命中 → 交 Agent")
        return RouteResult(handled=False, intent=Intent.FAQ, needs_agent=True)

    # ── 管线: product ─────────────────────────────────────────────────

    async def _handle_product(self, msg: str, entities: dict, sk: str) -> RouteResult:
        """商品管线：RAG 商品搜索 → RAG FAQ 降级 → Agent 兜底。"""
        print(f"  [路由 → product] RAG 语义搜索")
        if self.kb is None:
            return RouteResult(handled=False, intent=Intent.PRODUCT, needs_agent=True)

        hits = self.kb.search_products(msg, n_results=3)
        if hits and hits[0]["score"] > 0.3:
            result = "为您找到以下相关商品：\n\n"
            for h in hits[:3]:
                result += f"**{h.get('name', '')}**\n{h['content'][:200]}\n\n"
            return RouteResult(handled=True, intent=Intent.PRODUCT, reply=result.strip())

        print(f"  [路由 → product] RAG 商品未命中（最高 {hits[0]['score'] if hits else 0}），尝试 FAQ")
        rag_hit = await self._rag_fallback(msg)
        if rag_hit:
            return rag_hit
        return RouteResult(handled=False, intent=Intent.PRODUCT, needs_agent=True)

    # ── 管线: order_query ─────────────────────────────────────────────

    async def _handle_order_query(self, msg: str, entities: dict, sk: str) -> RouteResult:
        oid = entities.get("order_id") or self._get_ctx_order_id(sk)
        if not oid:
            print(f"  [路由 → order_query] 无订单号 → Agent")
            return RouteResult(handled=False, intent=Intent.ORDER_QUERY, needs_agent=True)

        print(f"  [路由 → order_query] 查订单 {oid}")
        try:
            result = await self.tools.execute("order_query", {"order_id": oid})
            return RouteResult(handled=True, intent=Intent.ORDER_QUERY,
                             reply=result, entities={"order_id": oid})
        except Exception as exc:
            print(f"  [路由 → order_query] 失败: {exc}")
            return RouteResult(handled=False, intent=Intent.ORDER_QUERY,
                             entities={"order_id": oid}, needs_agent=True)

    # ── 管线: logistics ───────────────────────────────────────────────

    async def _handle_logistics(self, msg: str, entities: dict, sk: str) -> RouteResult:
        oid = entities.get("order_id") or self._get_ctx_order_id(sk)
        if not oid:
            print(f"  [路由 → logistics] 无订单号 → Agent")
            return RouteResult(handled=False, intent=Intent.LOGISTICS, needs_agent=True)

        print(f"  [路由 → logistics] 查物流 {oid}")
        try:
            result = await self.tools.execute("order_query", {"order_id": oid})
            # order_query 返回的数据已包含物流字段，直接返回
            return RouteResult(handled=True, intent=Intent.LOGISTICS,
                             reply=result, entities={"order_id": oid})
        except Exception as exc:
            print(f"  [路由 → logistics] 失败: {exc}")
            return RouteResult(handled=False, intent=Intent.LOGISTICS,
                             entities={"order_id": oid}, needs_agent=True)

    # ── 管线: after_sales ─────────────────────────────────────────────

    async def _handle_after_sales(self, msg: str, entities: dict, sk: str) -> RouteResult:
        oid = entities.get("order_id") or self._get_ctx_order_id(sk)

        # 检测是哪种售后
        action = "退货"
        for kw in ["退款", "退钱"]:
            if kw in msg:
                action = "退款"
                break
        for kw in ["换货", "我要换", "想换"]:
            if kw in msg:
                action = "换货"
                break

        if not oid:
            # 没有订单号 → 反问
            print(f"  [路由 → after_sales] {action} 无订单号 → 反问")
            reply = ACTION_PROMPTS.get(action, f"好的～要帮你处理{action}。请提供你的订单号（5位数字）～")
            return RouteResult(handled=True, intent=Intent.AFTER_SALES, reply=reply)

        # 有订单号 → 查订单 + 交给 Agent 后续处理
        print(f"  [路由 → after_sales] {action} + 订单号 {oid} → 查库后交 Agent")
        try:
            order_info = await self.tools.execute("order_query", {"order_id": oid})
        except Exception as exc:
            order_info = f"订单查询出错: {exc}"

        return RouteResult(
            handled=True,  # 路由处理了（查了订单）
            intent=Intent.AFTER_SALES,
            reply=order_info,  # 订单信息作为上下文
            entities={"order_id": oid, "action": action},
            needs_agent=True,  # 但后续需要 Agent 处理退货/退款流程
        )

    # ── 管线: complaint ───────────────────────────────────────────────

    async def _handle_complaint(self, msg: str, entities: dict, sk: str) -> RouteResult:
        print(f"  [路由 → complaint] 投诉 → 转人工")
        return RouteResult(
            handled=True,
            intent=Intent.COMPLAINT,
            reply=(
                "非常抱歉给您带来不好的体验！我已经记录下您的反馈，"
                "会优先安排人工客服跟进处理。\n\n"
                "在此期间，如果您方便的话，可以简单描述一下遇到的问题，"
                "这会帮助我们更快地为您解决～"
            ),
            needs_agent=False,
        )

    # ── 管线: complex（兜底）──────────────────────────────────────────

    async def _handle_complex(self, msg: str, entities: dict, sk: str) -> RouteResult:
        print(f"  [路由 → complex] 无法分类 → 交给 Agent 处理")
        return RouteResult(
            handled=False,
            intent=Intent.COMPLEX,
            entities=entities,
            needs_agent=True,
        )

    # ── Layer 3: LLM 分类 ─────────────────────────────────────────────

    async def _llm_classify(self, msg: str) -> Intent:
        """用 LLM 做一次轻量分类（~50 token），只输出意图标签。"""
        try:
            response = await self.provider.chat(
                messages=[{
                    "role": "user",
                    "content": CLASSIFY_PROMPT.format(message=msg[:200]),
                }],
                tools=None,
            )
            if response.content:
                label = response.content.strip().lower()
                # 尝试匹配已知意图
                for intent in Intent:
                    if intent.value in label:
                        return intent
        except Exception:
            pass
        return Intent.COMPLEX

    # ── 辅助方法 ──────────────────────────────────────────────────────

    async def _rag_fallback(self, msg: str) -> RouteResult | None:
        """RAG 语义搜索降级：在 FAQ + 商品向量库中搜索。

        用在 SQL ILIKE 没命中时做语义兜底——向量模型能理解"发烫"和"散热"的关联，
        这是 SQL 精确匹配做不到的。

        Returns:
            RouteResult 若命中（score > 0.35），None 若也没命中。
        """
        if self.kb is None:
            return None
        hits = self.kb.search_all(msg, n_results=3)
        if not hits or hits[0]["score"] < 0.35:
            return None
        top = hits[0]
        label = top.get("question") or top.get("name", "")
        # 区分 FAQ 命中和商品命中
        source = "FAQ" if "faq_id" in top else "商品"
        result = (
            f"根据您的描述，在{source}库中找到相关内容（语义匹配，相似度 {top['score']}）：\n\n"
            f"**{label}**\n{top['content'][:350]}"
        )
        print(f"  [路由 → faq] RAG 命中: '{label}' score={top['score']}")
        return RouteResult(handled=True, intent=Intent.FAQ, reply=result)

    def _get_ctx_order_id(self, session_key: str) -> str | None:
        """从会话上下文读取订单号。"""
        if not self._get_session or not session_key:
            return None
        sc = self._get_session(session_key)
        return sc.store.get(session_key, "order_id", "") or None

    # ── 统计（指标系统）───────────────────────────────────────────────

    def record_latency(self, intent: str, ms: float):
        """记录一次请求的响应时间。"""
        if intent in self._latency:
            self._latency[intent].append(ms)

    def record_handoff(self):
        """记录一次转人工。"""
        self._handoffs += 1

    @property
    def stats(self) -> dict:
        total = max(sum(self._stats.values()), 1)
        agent_calls = self._stats["complex"]
        agent_pct = round(agent_calls / total * 100, 1)

        # 各意图命中率
        intents_detail = {}
        for intent, count in self._stats.items():
            if intent == "llm_classify":
                continue
            lats = self._latency.get(intent, [])
            intents_detail[intent] = {
                "count": count,
                "pct": round(count / total * 100, 1),
                "avg_ms": round(sum(lats) / max(len(lats), 1), 0),
            }

        # 整体平均响应时间
        all_lats = [ms for lats in self._latency.values() for ms in lats]
        avg_latency = round(sum(all_lats) / max(len(all_lats), 1), 0)

        return {
            "total_requests": total,
            "by_intent": intents_detail,
            "agent_calls": agent_calls,
            "agent_pct": agent_pct,
            "direct_pct": round(100 - agent_pct, 1),
            "handoffs": self._handoffs,
            "avg_latency_ms": avg_latency,
            "llm_classify_used": self._stats["llm_classify"],
        }

"""
CustomSystem — FastAPI + WebUI + PostgreSQL + Tools + RAG + 会话 + 置信度 + 画像
==================================================================================
默认访问 http://localhost:8765 即可在浏览器里和 Agent 对话。
"""

import sys
import os
from pathlib import Path

# Windows GBK 终端下 print 中文会炸，强制 stdout 用 UTF-8
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="WARNING")

load_dotenv()

import os
API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not API_KEY:
    print("[WARN] DEEPSEEK_API_KEY not set — LLM 调用将失败。请在 .env 中配置。")

# ── 自有模块 ────────────────────────────────────────────────────────
from core.bus import MessageBus
from core.loop import AgentLoop
from core.confidence import ConfidenceEvaluator
from core.context_store import ContextStore
from core.router import Router, RouteTarget
from core.fast_path import FastPathExecutor
from core.domain_agents import DomainAgentExecutor
from core.session_memory import SessionMemoryManager
from core.trace import TraceStore
from core.service import CustomerServiceEngine
from core.profile_manager import ProfileManager
from core.provider import DeepSeekProvider
from core.session_state import SessionContext
from core.persistence import SessionStore
from core.memory import MemoryConsolidator
from core.security import validate_message, SecurityError
from tools.registry import ToolRegistry

# ── 新增：数据库 + 工具 + RAG ───────────────────────────────────────
from db.connection import init_db
from db.seed import seed_all
from tools.faq_lookup import FaqLookupTool
from tools.human_handoff import HumanHandoffTool
from tools.order_query import OrderQueryTool
from tools.rag_search import RAGSearchTool
from rag.kb_store import KnowledgeBase
from rag.ingest import ingest_all

# ============================================================================
# 初始化数据库 + 注册工具
# ============================================================================
WORKSPACE = str(Path(__file__).parent / "workspace")

provider = DeepSeekProvider(
    api_key=API_KEY,
    api_base="https://api.deepseek.com",
    default_model="deepseek-chat",
)

bus = MessageBus()

# 创建向量知识库（测试/多实例可通过 QDRANT_PATH 使用独立目录）
kb = KnowledgeBase(persist_dir=os.getenv("QDRANT_PATH") or None)

# 创建工具注册表
tools = ToolRegistry()
tools.register(FaqLookupTool(kb=kb))    # kb 传入 → SQL 没命中时自动降级 RAG
tools.register(OrderQueryTool())
tools.register(RAGSearchTool(kb))
tools.register(HumanHandoffTool())

# 创建会话上下文存储（短期记忆）+ 持久化 + 记忆系统
ctx_store = ContextStore()
session_store = SessionStore(Path(WORKSPACE) / "sessions")
confidence = ConfidenceEvaluator()
memory = MemoryConsolidator(provider)

loop = AgentLoop(
    bus=bus,
    provider=provider,
    workspace_path=WORKSPACE,
    tools=tools,
    session_store=session_store,
)

def _session_factory(session_key: str) -> SessionContext:
    return SessionContext(ctx_store, session_key)

# 统一路由 + 确定性 FastPath + 三个专业 ReAct Agent
router = Router(provider=provider, session_factory=_session_factory)
fast_path = FastPathExecutor(tools, kb=kb)
domain_agents = DomainAgentExecutor(loop, tools)
session_memory = SessionMemoryManager(ctx_store, session_store)
trace_store = TraceStore()
engine = CustomerServiceEngine(
    router, fast_path, domain_agents, tools, session_memory, trace_store
)

print(f"[OK] Agent ready  |  Model: {provider.default_model}")
print(f"     Workspace: {WORKSPACE}")
print(f"     Tools: {', '.join(tools.tool_names)}")
print("     Targets: fast_path | presales | in_sales | aftersales | human")

# ── 对话日志（内存中，保留最近 200 条）────────────────────────────
from collections import deque
from datetime import datetime
conv_log: deque[dict] = deque(maxlen=200)

# ============================================================================
# FastAPI 服务
# ============================================================================
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from fastapi.middleware.cors import CORSMiddleware

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan —— python server.py 和 uvicorn server:app 均生效。"""
    # DB / RAG 初始化（失败不阻塞启动，请求时会明确报错）
    try:
        await init_db()
        await seed_all()
        await ingest_all(kb)
        print("  DB + RAG initialized.")
    except Exception as exc:
        print(f"  [WARN] DB/RAG 初始化失败: {exc}")
        print(f"  [WARN] 客服聊天功能将不可用，但 admin 面板仍可访问。")

    # 会话恢复
    try:
        sessions = await session_store.list_sessions()
        restored = 0
        for filename_key in sessions:
            ctx = await session_store.load_context(filename_key)
            if ctx:
                original_key = ctx.pop("_session_key", filename_key)
                for field, value in ctx.items():
                    ctx_store.set(original_key, field, value)
                restored += 1
        if restored:
            print(f"  Sessions restored: {restored}")
    except Exception:
        pass  # 会话恢复失败不阻塞启动

    print()
    print("=" * 60)
    print("  Server startup complete.")
    print(f"  Tools ({len(tools)}): {', '.join(tools.tool_names)}")
    print("=" * 60)

    try:
        yield
    finally:
        kb.close()


app = FastAPI(title="CustomSystem Chat", version="0.4.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8765",
        "http://127.0.0.1:8765",
        "http://localhost:9000",
        "http://127.0.0.1:9000",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()
if not ADMIN_TOKEN:
    print("[WARN] ADMIN_TOKEN not set - admin data APIs are disabled.")

from fastapi import Header, HTTPException

async def _require_admin(x_admin_token: str = Header(default="")):
    """简易 admin 鉴权。生产环境请换为正式的认证中间件。"""
    if not ADMIN_TOKEN or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden: invalid admin token")

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>static/index.html 未找到</h1>"


class ChatRequest(BaseModel):
    message: str
    session_key: str = "web:default"


class ChatResponse(BaseModel):
    reply: str
    session_key: str


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    # ── 安全校验 ──
    try:
        msg = validate_message(req.message)
    except SecurityError as exc:
        return ChatResponse(reply=f"⚠️ {exc}", session_key=req.session_key)

    sk = req.session_key
    sc = _session_factory(sk)
    previous_intent = ctx_store.get(sk, "intent", "")
    closing_message = _is_closing_message(msg)
    print(f"\n{'='*50}")
    print(f"[收到消息] {msg[:80]}{'...' if len(msg) > 80 else ''}  |  阶段: {sc.phase.value}")

    # ---- 加载长期画像 + 短期上下文 ----
    phone = await ProfileManager.resolve_key(_extract_phone(msg, sk))
    profile_text = ""
    if phone:
        ctx_store.set(sk, "customer_key", phone)
        profile = await ProfileManager.get_or_create(phone)
        profile_text = ProfileManager.to_prompt_text(profile)

    t0 = datetime.now()
    service_result = await engine.process(msg, sk, profile_text=profile_text)
    decision = service_result.decision
    target = service_result.final_target
    reply = service_result.reply
    memory_intent = (
        previous_intent
        if closing_message and previous_intent
        else decision.intent.value
    )
    if phone:
        await ProfileManager.touch_interaction(phone, memory_intent)
        events = set(ctx_store.get(sk, "profile_events", []) or [])
        action = (ctx_store.get(sk, "slots", {}) or {}).get("action")
        if decision.intent.value == "after_sales" and action == "退款" and "refund" not in events:
            await ProfileManager.note_refund(phone)
            events.add("refund")
            ctx_store.set(sk, "profile_events", sorted(events))
            await session_store.save_context(sk, ctx_store.get_all(sk))
    print(
        f"[路由] target={target.value} intent={decision.intent.value} "
        f"confidence={decision.confidence:.2f} reason={decision.reason}"
    )

    # FastPath 与人工路径不需要 Agent 置信度评分。
    if not service_result.used_agent:
        if target is RouteTarget.HUMAN:
            if phone and decision.intent.value == "complaint":
                await ProfileManager.note_complaint(phone)
                print(f"  [客户记忆] 投诉次数 +1 ({phone[:7]}...)")
            await _consolidate_memory(sk, phone, intent=memory_intent)
        elif phone and closing_message:
            await _consolidate_memory(sk, phone, intent=memory_intent)
        _log_conversation(sk, msg, reply, target.value, None, t0)
        return ChatResponse(reply=reply, session_key=sk)

    # ---- 置信度评估 ----
    tools_used = list(service_result.tools_called)
    tool_ok = len(tools_used) > 0 and not any(
        kw in reply for kw in ["未找到", "没有找到", "不存在", "(FAQ 知识库中没有"]
    )
    had_error = reply.startswith("抱歉，AI 服务") or reply.startswith("LLM 调用失败")

    result = confidence.evaluate(
        user_message=msg,
        agent_reply=reply,
        tools_called=tools_used if tools_used else [],
        tool_success=tool_ok,
        had_error=had_error,
    )
    print(f"  [置信度] {result.score} ({result.level}) — {result.reason}")
    if result.needs_human:
        print(f"  [告警] 低置信度，需人工关注！")
        print(f"  [接管摘要]\n{result.summary}")
        router.record_handoff()
        await _consolidate_memory(sk, phone, intent=memory_intent)

    _log_conversation(sk, msg, reply, target.value, result, t0)
    return ChatResponse(reply=reply, session_key=sk)


# ====================================================================
# 对话日志
# ====================================================================

def _log_conversation(session_key, msg, reply, source, confidence_result, t0):
    """记录一条对话到内存日志。"""
    took_ms = int((datetime.now() - t0).total_seconds() * 1000) if t0 else 0
    entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "session": session_key[-12:],
        "message": msg[:60],
        "reply": (reply or "")[:60],
        "source": source,
        "confidence": confidence_result.score if confidence_result else None,
        "needs_human": confidence_result.needs_human if confidence_result else False,
        "took_ms": took_ms,
    }
    conv_log.append(entry)


# ====================================================================
# Admin API
# ====================================================================

@app.get("/admin")
async def admin_page():
    """后台页面本身公开访问（去掉页面级 token），但页面里的数据接口
    /api/admin/* 仍需 X-Admin-Token 鉴权——页面加载后由 JS 携带 token 拉数据。
    这样聊天页一个链接就能跳进来，不必处理浏览器无法给普通跳转附加请求头的问题。"""
    html = STATIC_DIR / "admin.html"
    if html.exists():
        return HTMLResponse(html.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>admin.html not found</h1>")


@app.get("/api/admin/log")
async def admin_log(_token: str = Header(alias="X-Admin-Token", default="")):
    if not ADMIN_TOKEN or _token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    return {"log": list(conv_log), "total": len(conv_log)}


@app.get("/api/admin/stats")
async def admin_stats(_token: str = Header(alias="X-Admin-Token", default="")):
    if not ADMIN_TOKEN or _token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    return {**router.stats, "conversation_log_size": len(conv_log)}


@app.get("/api/admin/sessions")
async def admin_sessions(_token: str = Header(alias="X-Admin-Token", default="")):
    if not ADMIN_TOKEN or _token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    sessions = []
    for sk in await ctx_store.all_keys():
        ctx = ctx_store.get_all(sk)
        if ctx:
            sessions.append({"key": sk[-16:], **ctx})
    return {"sessions": sessions, "count": len(sessions)}


@app.get("/api/admin/traces")
async def admin_traces(_token: str = Header(alias="X-Admin-Token", default="")):
    if not ADMIN_TOKEN or _token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    return {"traces": trace_store.recent(), "count": len(trace_store)}


# ====================================================================
# 上下文更新（每次对话后提取关键实体）
# ====================================================================

def _extract_phone(msg: str, session_key: str) -> str | None:
    """从消息或上下文中提取手机号——多重校验避免误识别。

    误识别示例（已修复）：
      用户发 "88001" → 旧逻辑匹配 "8001" → 创建错误画像 ***8001
      现在：88001 是 5 位订单号 → 不提取
    """
    # 优先从上下文取（之前对话中已确认的手机号）
    customer_key = ctx_store.get(session_key, "customer_key", "")
    if customer_key:
        return customer_key

    import re

    # 必须有手机相关上下文关键词，才从消息提取
    phone_keywords = ["手机", "电话", "尾号", "后四位", "验证", "号码"]
    has_context = any(kw in msg for kw in phone_keywords)

    if has_context:
        # 查找明确标注的手机尾号，如 "尾号8001"、"后四位 8001"
        m = re.search(r'(?:尾号|后四位|手机尾号|号码?)\s*(\d{4})', msg)
        if m:
            return "***" + m.group(1)
        # 含 5 位订单号时，不把订单号末四位误识别为手机尾号。
        if re.search(r'(?<!\d)\d{5}(?!\d)', msg):
            return None
        # 消息末尾独立出现的 4 位数字，且不是 5 位数字的后缀
        m = re.search(r'(?:^|\s)(\d{4})\s*$', msg)
        if m:
            return "***" + m.group(1)

    return None


def _is_closing_message(msg: str) -> bool:
    normalized = msg.strip().lower().rstrip("！!。～~")
    exact = {"谢谢", "好的", "好", "明白了", "解决了", "没问题了", "ok"}
    return normalized in exact or (
        len(normalized) <= 16
        and any(marker in normalized for marker in ("谢谢", "明白了", "解决了", "没问题了"))
    )


async def _consolidate_memory(session_key: str, phone: str | None, intent: str = ""):
    """将当前会话对话历史压缩为摘要，存入顾客画像。

    触发时机：低置信度/转人工（对话自然结束点）。
    类似 nanobot 的 Consolidator，但按会话边界触发而非 token 预算。
    """
    try:
        history = await loop._get_history(session_key)
        if len(history) < 3:
            return

        summary = await memory.summarize(history)
        if not summary:
            summary = MemoryConsolidator.fallback_summary(history)

        if phone and summary:
            await ProfileManager.summarize_conversation(phone, summary, intent=intent)
            print(f"  [记忆] 对话摘要已存入顾客画像 ({phone[:7]}...) -> {intent}")
    except Exception as exc:
        print(f"  [记忆] 摘要失败: {exc}")


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "model": provider.default_model,
        "tools": tools.tool_names,
        "router": {
            "total": router.stats["total_requests"],
            "agent_pct": router.stats["agent_pct"],
            "direct_pct": router.stats["direct_pct"],
        },
    }


# ============================================================================
# 启动
# ============================================================================
if __name__ == "__main__":
    import uvicorn
    # 注意：传 app 对象而非 "server:app" 字符串。
    # 字符串形式会让 uvicorn 重新 import 本模块，导致模块顶层的 KnowledgeBase()
    # 被构造两次，两个嵌入式 Qdrant 客户端抢同一数据目录的文件锁而崩溃。
    # 传对象只构造一次。代价是失去 reload 热重载，但这里本就 reload=False。
    uvicorn.run(
        app,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8765")),
        log_level="warning",
    )

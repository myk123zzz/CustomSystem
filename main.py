"""
CustomSystem — 第 4 步：自有 Agent + PostgreSQL + 工具
==========================================================
终端版入口。Agent 可以调用 faq_lookup / order_query 查数据库。
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="WARNING")

load_dotenv()

import os
API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not API_KEY:
    print("[ERROR] 未找到 DEEPSEEK_API_KEY")
    exit(1)

from core.bus import MessageBus
from core.loop import AgentLoop
from core.provider import DeepSeekProvider
from tools.registry import ToolRegistry
from db.connection import init_db
from db.seed import seed_all
from tools.faq_lookup import FaqLookupTool
from tools.order_query import OrderQueryTool

WORKSPACE = str(Path(__file__).parent / "workspace")

tools = ToolRegistry()
tools.register(FaqLookupTool())
tools.register(OrderQueryTool())

loop = AgentLoop(
    bus=MessageBus(),
    provider=DeepSeekProvider(
        api_key=API_KEY,
        api_base="https://api.deepseek.com",
        default_model="deepseek-chat",
    ),
    workspace_path=WORKSPACE,
    tools=tools,
)


async def main():
    # 初始化数据库（init_db + seed_all 必须在同一个事件循环内）
    await init_db()
    await seed_all()
    # 清理前一个事件循环遗留的连接，避免后续查询出错
    from db.connection import _engine
    await _engine.dispose()

    print("=" * 60)
    print("  CustomSystem — 第 4 步：Agent + PostgreSQL + 工具")
    print(f"  工具: {', '.join(tools.tool_names)}")
    print("=" * 60)

    while True:
        try:
            msg = input("\n[You]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye~")
            break

        if not msg:
            continue
        if msg.lower() in ("/exit", "/quit"):
            print("Bye~")
            break

        print("Agent thinking...")
        response = await loop.process_direct(content=msg, session_key="cli:main")
        if response and response.final_content:
            print(f"\n[Agent]: {response.final_content}")
        else:
            print("\n[Agent]: (no reply)")


if __name__ == "__main__":
    asyncio.run(main())

"""
数据库连接管理
================
使用 asyncpg（异步 PostgreSQL 驱动）+ SQLAlchemy 2.0 async 模式。

设计：
  - NullPool：每次请求新建连接，用完释放。
    因为 startup/lifespan 可能在不同事件循环执行，NullPool 避免连接池跨循环问题。
  - 换数据库：设置环境变量 DATABASE_URL 或直接改下方的默认值。
"""

import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://localhost:5432/cssdb")

_engine = create_async_engine(DATABASE_URL, echo=False, poolclass=NullPool)

SessionLocal = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """初始化数据库——创建所有表。"""
    from db.models import Base
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def get_session() -> AsyncSession:
    """获取一个异步数据库 session（新建连接）。"""
    return SessionLocal()

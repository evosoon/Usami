"""
Usami — Memory Store
数据库初始化 + 持久化抽象

MVP 阶段:
- PostgreSQL: Checkpoint 持久化 + 任务日志 + HiTL 事件
- Redis: 工作记忆 + 事件总线
"""

from __future__ import annotations

import structlog
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

logger = structlog.get_logger()


# ============================================
# SQLAlchemy Models
# ============================================

class Base(DeclarativeBase):
    pass


class TaskLog(Base):
    """任务执行日志"""
    __tablename__ = "task_logs"

    id = Column(String, primary_key=True)
    thread_id = Column(String, index=True)
    task_id = Column(String)
    persona = Column(String)
    status = Column(String)
    summary = Column(Text)
    full_result = Column(Text)
    confidence = Column(Float)
    cost_usd = Column(Float, default=0.0)
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, server_default=func.now())


class HiTLEventLog(Base):
    """HiTL 事件日志（为 Progressive Trust 埋数据管道）"""
    __tablename__ = "hitl_events"

    id = Column(String, primary_key=True)
    request_id = Column(String, unique=True, index=True)
    hitl_type = Column(String)
    trigger = Column(String)
    context = Column(JSON)
    response = Column(String, nullable=True)
    feedback = Column(Text, nullable=True)
    response_time_ms = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class RoutingLog(Base):
    """Model Router 路由日志"""
    __tablename__ = "routing_logs"

    id = Column(String, primary_key=True)
    task_type = Column(String)
    model_tier = Column(String)
    model_name = Column(String)
    prompt_tokens = Column(Float, default=0)
    completion_tokens = Column(Float, default=0)
    latency_ms = Column(Float, default=0)
    cost_usd = Column(Float, default=0)
    success = Column(String, default="true")
    created_at = Column(DateTime, server_default=func.now())


class Document(Base):
    """知识库文档 (RAG 向量检索)"""
    __tablename__ = "documents"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    source = Column(String)  # URL, file path, etc.
    embedding = Column(Vector(1536))  # text-embedding-3-small dimension
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class User(Base):
    """User accounts for authentication"""
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="user")
    is_active = Column(Boolean, default=True, server_default="true")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class PushSubscription(Base):
    """Push notification subscriptions (Web Push API)"""
    __tablename__ = "push_subscriptions"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    endpoint = Column(String, nullable=False, unique=True)
    p256dh = Column(String, nullable=False)
    auth_key = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class Event(Base):
    """Persisted SSE events — single source of truth for all task state"""
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("thread_id", "seq", name="uq_events_thread_seq"),
    )

    id = Column(String, primary_key=True)
    thread_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    event_type = Column(String, nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, server_default=func.now())


# ============================================
# Database Initialization
# ============================================

_engine = None
_session_factory = None


async def init_database(database_url: str) -> None:
    """初始化数据库连接 + 执行 Alembic 迁移"""
    global _engine, _session_factory

    # SQLAlchemy 需要 async driver
    async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")

    _engine = create_async_engine(async_url, echo=False)
    _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

    # 使用 Alembic 管理 schema（同步 psycopg 驱动）
    from pathlib import Path

    from alembic.config import Config

    from alembic import command

    alembic_ini = Path(__file__).parent.parent / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini))
    command.upgrade(alembic_cfg, "head")

    logger.info("database_initialized", url=database_url[:30] + "...")


async def init_database_for_tests(database_url: str) -> None:
    """测试专用: 使用 create_all() 快速建表，跳过 Alembic"""
    global _engine, _session_factory

    async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    _engine = create_async_engine(async_url, echo=False)
    _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("test_database_initialized")


def get_session() -> AsyncSession:
    """获取数据库会话"""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _session_factory()

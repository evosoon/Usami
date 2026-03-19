"""
Usami — Personal AI Operating System
FastAPI 入口文件 (v2 Refactor)

v2 架构变化:
- Worker 进程独立执行 LangGraph 图（不在 API 进程内执行）
- 事件通过 PostgreSQL + pg_notify 和 Redis pub/sub 分发
- 删除 active_tasks, sse_event_callback, on_event 参数

启动方式: uvicorn main:app --reload
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from agents.boss import build_boss_graph
from api.admin_routes import router as admin_router
from api.auth_routes import router as auth_router
from api.notification_routes import router as notification_router
from api.routes import router as api_router
from api.sse import SSEConnectionManager
from api.sse import router as sse_router
from core.auth import init_auth, seed_admin_user
from core.config import load_config
from core.memory import init_database
from core.persona_factory import PersonaFactory
from core.push import init_push
from core.tool_registry import ToolRegistry, init_tool_config
from scheduler.cron import init_scheduler

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理 (v2)"""
    # --- Startup ---
    config = load_config()
    app.state.config = config

    # 初始化数据库
    await init_database(config.database_url)

    # 初始化 Auth 模块
    init_auth(config)

    # 初始化 Push 通知模块
    init_push(config)

    # Seed admin user
    await seed_admin_user()

    # 初始化 Redis (非致命)
    redis_client = None
    try:
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(config.redis_url)
        await redis_client.ping()
        app.state.redis_client = redis_client
        logger.info("redis_initialized")

        # 初始化 EventBus (Redis Pub/Sub for webhook-triggered tasks)
        from scheduler.events import EventBus
        app.state.event_bus = EventBus(redis_client)
        logger.info("event_bus_initialized")
    except Exception as e:
        logger.warning("redis_init_skipped", error=str(e))
        redis_client = None

    # 初始化 Tool Registry（多源加载）
    init_tool_config(config)
    tool_registry = ToolRegistry()
    tool_registry.load_builtin_tools(config.tools)
    if config.mcp_servers:
        await tool_registry.load_mcp_tools(config.mcp_servers)
    app.state.tool_registry = tool_registry

    # 初始化 Persona Factory（配置驱动）
    persona_factory = PersonaFactory(
        personas_config=config.personas,
        tool_registry=tool_registry,
        model_router_config=config.routing,
        litellm_url=config.litellm_url,
        litellm_master_key=config.litellm_master_key,
    )
    app.state.persona_factory = persona_factory

    # 初始化 SSE 连接管理器 (v2: 仍用于 legacy SSEConnectionManager, 主要用途是 health check)
    sse_manager = SSEConnectionManager(redis_client=redis_client)
    app.state.sse_manager = sse_manager

    # NOTE: Redis subscription for SSE is no longer needed in v2 architecture
    # (Worker uses pg_notify directly). The SSEConnectionManager is retained
    # for backwards compatibility only.

    # 构建 Boss Graph (v2: 只需 persona_factory 和 checkpointer)
    # Worker 进程会独立构建和执行图，这里主要用于 health check 和 scheduler
    checkpointer = None
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        checkpointer_cm = AsyncPostgresSaver.from_conn_string(config.database_url)
        checkpointer = await checkpointer_cm.__aenter__()
        await checkpointer.setup()
        app.state.checkpointer_cm = checkpointer_cm
        logger.info("checkpoint_saver_initialized")
    except Exception as e:
        logger.warning("checkpoint_saver_skipped", error=str(e))

    # v2: build_boss_graph 只接受 persona_factory 和 checkpointer
    boss_graph = build_boss_graph(
        persona_factory=persona_factory,
        checkpointer=checkpointer,
    )
    app.state.boss_graph = boss_graph

    # 初始化定时调度器 (v2: scheduler 可以通过 pg_notify 触发任务)
    scheduler = init_scheduler(config.scheduler, boss_graph=boss_graph)
    scheduler.start()
    app.state.scheduler = scheduler

    yield

    # --- Shutdown ---
    scheduler.shutdown()

    # Cleanup checkpointer context manager
    if hasattr(app.state, 'checkpointer_cm'):
        try:
            await app.state.checkpointer_cm.__aexit__(None, None, None)
        except Exception as e:
            logger.warning("checkpointer_cleanup_failed", error=str(e))

    # Cleanup Redis
    if redis_client:
        try:
            await redis_client.close()
        except Exception as e:
            logger.warning("redis_cleanup_failed", error=str(e))


app = FastAPI(
    title="Usami",
    description="Personal AI Operating System — 技术调研 + 知识凝练",
    version="0.1.0",
    lifespan=lifespan,
)

# Rate limiting
from core.rate_limit import limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS
_cors_origins = os.environ.get("CORS_ORIGINS", "http://localhost:42000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(auth_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(notification_router, prefix="/api/v1")
app.include_router(api_router, prefix="/api/v1")
app.include_router(sse_router, prefix="/api/v1")


@app.get("/health")
async def health(request: Request):
    """健康检查 — 含 LiteLLM 连通性 + 断路器状态"""
    checks: dict[str, Any] = {"service": "Usami", "status": "ok"}

    # LiteLLM 连通性
    litellm_url = getattr(request.app.state, "config", None)
    if litellm_url:
        litellm_url = request.app.state.config.litellm_url
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{litellm_url}/health")
                checks["litellm"] = "ok" if resp.status_code == 200 else "degraded"
        except Exception:
            checks["litellm"] = "unreachable"
            checks["status"] = "degraded"

    # 断路器状态
    persona_factory = getattr(request.app.state, "persona_factory", None)
    if persona_factory:
        cb = persona_factory.model_router.circuit_breaker
        checks["circuit_breaker"] = cb.state
        if cb.state == "open":
            checks["status"] = "degraded"

    # Redis 状态
    redis_client = getattr(request.app.state, "redis_client", None)
    if redis_client:
        try:
            await redis_client.ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "degraded"
            checks["status"] = "degraded"
    else:
        checks["redis"] = "unavailable"

    # SSE 连接数
    sse_manager = getattr(request.app.state, "sse_manager", None)
    if sse_manager:
        checks["sse_connections"] = sse_manager.active_connections

    return checks

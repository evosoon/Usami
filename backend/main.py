"""
Usami — Personal AI Operating System
FastAPI 入口文件

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
from core.event_store import persist_event
from core.hitl import HiTLGateway
from core.memory import init_database
from core.persona_factory import PersonaFactory
from core.push import init_push, send_push
from core.tool_registry import ToolRegistry, init_tool_config
from scheduler.cron import init_scheduler

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
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

        # 初始化 EventBus (仅创建实例，MVP 暂不启动监听)
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

    # 初始化 HiTL Gateway
    hitl_gateway = HiTLGateway(
        budget_config=config.routing.get("budget", {})
    )
    app.state.hitl_gateway = hitl_gateway

    # 初始化 SSE 连接管理器 (在 boss_graph 之前, 用于回调)
    sse_manager = SSEConnectionManager(redis_client=redis_client)
    app.state.sse_manager = sse_manager

    # Start Redis subscription for cross-worker SSE distribution
    if redis_client:
        import asyncio as _asyncio
        _sse_sub_task = _asyncio.create_task(sse_manager.start_subscription())
        app.state._sse_sub_task = _sse_sub_task

    # 构建 Boss Graph（带 Checkpoint 持久化 + SSE 事件回调）
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

    async def sse_event_callback(event_type: str, data: dict) -> None:
        """Boss Graph → persist event → push to SSE connections + Push notifications"""
        thread_id = data.get("thread_id", "")

        # Look up user_id from active_tasks
        task_record = app.state.active_tasks.get(thread_id, {})
        user_id = task_record.get("user_id") if isinstance(task_record, dict) else None
        if not user_id:
            logger.warning("event_no_user", event_type=event_type, thread_id=thread_id)
            return

        # Persist to DB
        try:
            persisted = await persist_event(thread_id, user_id, event_type, data)
        except Exception as e:
            logger.error("event_persist_failed", event_type=event_type, error=str(e))
            return

        # Route to user's SSE connections (via Redis for multi-worker)
        await sse_manager.broadcast_event(user_id, persisted)

        # Send browser push notifications for key events
        if event_type in ("task.completed", "task.failed", "hitl.request"):
            push_titles = {
                "task.completed": "任务完成",
                "task.failed": "任务失败",
                "hitl.request": "需要您的确认",
            }
            push_bodies = {
                "task.completed": data.get("result", "")[:200] if data.get("result") else "任务已完成",
                "task.failed": data.get("error", "任务执行失败"),
                "hitl.request": "有一个任务需要您的人工审核",
            }
            try:
                await send_push(
                    user_id=user_id,
                    title=push_titles[event_type],
                    body=push_bodies[event_type],
                    url=f"/tasks/{thread_id}" if thread_id else "/chat",
                )
            except Exception as e:
                logger.warning("push_notification_failed", event=event_type, error=str(e))

    boss_graph = build_boss_graph(
        persona_factory=persona_factory,
        hitl_gateway=hitl_gateway,
        checkpointer=checkpointer,
        on_event=sse_event_callback,
    )
    app.state.boss_graph = boss_graph

    # 活跃任务追踪 (thread_id → {user_id, task})
    app.state.active_tasks: dict[str, Any] = {}

    # 初始化定时调度器
    scheduler = init_scheduler(config.scheduler, boss_graph=boss_graph, active_tasks=app.state.active_tasks)
    scheduler.start()
    app.state.scheduler = scheduler

    yield

    # --- Shutdown ---
    scheduler.shutdown()

    # Cancel SSE Redis subscription
    sse_sub = getattr(app.state, "_sse_sub_task", None)
    if sse_sub and not sse_sub.done():
        sse_sub.cancel()

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

"""
AgenticOS — Personal AI Operating System
FastAPI 入口文件

启动方式: uvicorn main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import httpx
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router as api_router
from api.websocket import router as ws_router, ConnectionManager
from core.config import load_config
from core.memory import init_database
from core.tool_registry import ToolRegistry
from core.persona_factory import PersonaFactory
from core.hitl import HiTLGateway
from agents.boss import build_boss_graph
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
    )
    app.state.persona_factory = persona_factory

    # 初始化 HiTL Gateway
    hitl_gateway = HiTLGateway(
        budget_config=config.routing.get("budget", {})
    )
    app.state.hitl_gateway = hitl_gateway

    # 初始化 WebSocket 连接管理器 (在 boss_graph 之前, 用于回调)
    ws_manager = ConnectionManager()
    app.state.ws_manager = ws_manager

    # 构建 Boss Graph（带 Checkpoint 持久化 + WebSocket 事件回调）
    checkpointer = None
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        checkpointer_cm = AsyncPostgresSaver.from_conn_string(config.database_url)
        checkpointer = await checkpointer_cm.__aenter__()
        await checkpointer.setup()
        app.state.checkpointer_cm = checkpointer_cm  # 保存 context manager 用于 cleanup
        logger.info("checkpoint_saver_initialized")
    except Exception as e:
        logger.warning("checkpoint_saver_skipped", error=str(e))

    async def ws_event_callback(event_type: str, data: dict) -> None:
        """Boss Graph → WebSocket 事件回调"""
        await ws_manager.broadcast({"type": event_type, **data})

    boss_graph = build_boss_graph(
        persona_factory=persona_factory,
        hitl_gateway=hitl_gateway,
        checkpointer=checkpointer,
        on_event=ws_event_callback,
    )
    app.state.boss_graph = boss_graph

    # 活跃任务追踪 (thread_id → {task, result, error, status})
    app.state.active_tasks: dict[str, Any] = {}

    # 初始化定时调度器
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
    title="AgenticOS",
    description="Personal AI Operating System — 技术调研 + 知识凝练",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(api_router, prefix="/api/v1")
app.include_router(ws_router, prefix="/ws")


@app.get("/health")
async def health(request: Request):
    """健康检查 — 含 LiteLLM 连通性 + 断路器状态"""
    checks: dict[str, Any] = {"service": "AgenticOS", "status": "ok"}

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
    checks["redis"] = "ok" if redis_client else "unavailable"

    return checks

"""
Usami — 测试 Fixtures
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from core.hitl import HiTLGateway
from core.plan_validator import PlanValidator
from core.state import (
    Task,
    TaskOutput,
    TaskPlan,
    UserProfile,
    UserRole,
)

# ============================================
# Persona & Validator Fixtures
# ============================================

AVAILABLE_PERSONAS = ["boss", "researcher", "writer", "analyst"]


@pytest.fixture
def available_personas() -> list[str]:
    return AVAILABLE_PERSONAS


@pytest.fixture
def validator(available_personas) -> PlanValidator:
    return PlanValidator(available_personas=available_personas)


@pytest.fixture
def hitl_gateway() -> HiTLGateway:
    return HiTLGateway(budget_config={"max_cost_per_task_usd": 0.50})


# ============================================
# Sample Data Fixtures
# ============================================

@pytest.fixture
def simple_plan() -> TaskPlan:
    """简单的两任务线性计划"""
    return TaskPlan(
        plan_id="plan_test",
        user_intent="test intent",
        tasks=[
            Task(
                task_id="t1",
                title="Research",
                description="do research",
                assigned_persona="researcher",
                task_type="research",
            ),
            Task(
                task_id="t2",
                title="Write",
                description="write report",
                assigned_persona="writer",
                task_type="writing",
                dependencies=["t1"],
            ),
        ],
    )


@pytest.fixture
def task_output_high_confidence() -> TaskOutput:
    return TaskOutput(
        task_id="t1",
        persona="researcher",
        summary="Research results summary",
        full_result="Full research results with details",
        confidence=0.9,
    )


@pytest.fixture
def task_output_low_confidence() -> TaskOutput:
    return TaskOutput(
        task_id="t1",
        persona="researcher",
        summary="Uncertain results",
        full_result="Uncertain full results",
        confidence=0.3,
    )


# ============================================
# FastAPI Test Client Fixture
# ============================================

@pytest_asyncio.fixture
async def app_client():
    """FastAPI 测试客户端 — mock boss_graph 和其他依赖"""
    from httpx import ASGITransport, AsyncClient

    # 延迟导入避免启动副作用
    from main import app

    # Override auth dependency so existing tests don't need tokens
    from core.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: UserProfile(
        id="test_user",
        email="test@test.com",
        display_name="Test User",
        role=UserRole.ADMIN,
        is_active=True,
    )

    # Mock boss_graph
    mock_graph = AsyncMock()
    mock_graph.ainvoke = AsyncMock(return_value={"current_phase": "done"})
    mock_graph.aget_state = AsyncMock(return_value=MagicMock(
        values={
            "current_phase": "done",
            "task_plan": None,
            "task_outputs": {},
            "hitl_pending": [],
        }
    ))
    mock_graph.aupdate_state = AsyncMock()

    # Mock persona_factory
    mock_persona_factory = MagicMock()
    mock_persona_factory.list_personas.return_value = {
        "boss": {"name": "Boss", "role": "orchestrator", "description": "", "tools": [], "model": "strong"},
    }
    mock_router = MagicMock()
    mock_router.circuit_breaker = MagicMock(state="closed")
    mock_persona_factory.model_router = mock_router

    # Mock config
    mock_config = MagicMock()
    mock_config.litellm_url = "http://localhost:4000"

    # 注入 mock
    app.state.boss_graph = mock_graph
    app.state.hitl_gateway = HiTLGateway()
    app.state.active_tasks = {}
    mock_sse_manager = MagicMock()
    mock_sse_manager.send_to_user = AsyncMock()
    mock_sse_manager.broadcast_event = AsyncMock()
    mock_sse_manager.active_connections = 0
    app.state.sse_manager = mock_sse_manager
    app.state.persona_factory = mock_persona_factory
    app.state.tool_registry = MagicMock()
    app.state.tool_registry.list_tools.return_value = []
    app.state.scheduler = MagicMock()
    app.state.scheduler.get_jobs.return_value = []
    app.state.config = mock_config

    # Mock event_store functions to avoid DB dependency in route tests
    mock_persisted_event = MagicMock()
    mock_persisted_event.id = "evt_test"
    mock_persisted_event.thread_id = "thread_test"
    mock_persisted_event.user_id = "test_user"
    mock_persisted_event.seq = 1
    mock_persisted_event.event_type = "task.created"
    mock_persisted_event.payload = {}
    mock_persisted_event.created_at = ""

    transport = ASGITransport(app=app)
    with (
        patch("api.routes.persist_event", new=AsyncMock(return_value=mock_persisted_event)),
        patch("api.routes.get_thread_events", new=AsyncMock(return_value=[])),
        patch("api.routes.verify_thread_ownership", new=AsyncMock(return_value=True)),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, mock_graph

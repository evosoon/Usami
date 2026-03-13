"""
AgenticOS — 测试 Fixtures
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from core.state import (
    Task, TaskPlan, TaskOutput, TaskStatus,
    HiTLRequest, HiTLResponse, HiTLType,
)
from core.plan_validator import PlanValidator
from core.hitl import HiTLGateway


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
    from httpx import AsyncClient, ASGITransport

    # 延迟导入避免启动副作用
    from main import app

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
    mock_ws_manager = MagicMock()
    mock_ws_manager.broadcast = AsyncMock()
    mock_ws_manager.send_event = AsyncMock()
    app.state.ws_manager = mock_ws_manager
    app.state.persona_factory = mock_persona_factory
    app.state.tool_registry = MagicMock()
    app.state.tool_registry.list_tools.return_value = []
    app.state.scheduler = MagicMock()
    app.state.scheduler.get_jobs.return_value = []
    app.state.config = mock_config

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, mock_graph

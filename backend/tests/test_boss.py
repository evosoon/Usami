"""
Usami — Boss Graph 单元测试
测试 build_boss_graph + node 函数 (mock LLM)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agents.boss import build_boss_graph
from core.hitl import HiTLGateway
from core.persona_factory import PersonaFactory
from core.plan_validator import PlanValidator
from core.state import Task, TaskPlan, TaskStatus

# ============================================
# Fixtures
# ============================================

@pytest.fixture
def mock_persona_factory():
    """Mock PersonaFactory"""
    factory = MagicMock(spec=PersonaFactory)
    factory.available_personas = ["researcher", "writer", "analyst"]
    factory.get_persona.return_value = MagicMock()
    return factory


@pytest.fixture
def mock_hitl_gateway():
    """Mock HiTLGateway"""
    gateway = MagicMock(spec=HiTLGateway)
    gateway.evaluate.return_value = None  # 不触发 HiTL
    return gateway


@pytest.fixture
def mock_validator():
    """Mock PlanValidator"""
    validator = MagicMock(spec=PlanValidator)
    validator.validate.return_value = (True, [])  # 默认验证通过
    return validator


# ============================================
# build_boss_graph 测试
# ============================================

def test_build_boss_graph_returns_compiled_graph(mock_persona_factory, mock_hitl_gateway):
    """测试 build_boss_graph 返回编译后的 graph"""
    graph = build_boss_graph(
        persona_factory=mock_persona_factory,
        hitl_gateway=mock_hitl_gateway,
        checkpointer=None,
    )

    assert graph is not None
    # LangGraph 编译后的 graph 有 invoke 方法
    assert hasattr(graph, "ainvoke")
    assert hasattr(graph, "astream")


def test_build_boss_graph_with_checkpointer(mock_persona_factory, mock_hitl_gateway):
    """测试 build_boss_graph 接受 checkpointer 参数"""
    # LangGraph 要求 checkpointer 是 BaseCheckpointSaver 实例或 None
    # 这里只测试 None 情况，实际 checkpointer 需要真实实例
    graph = build_boss_graph(
        persona_factory=mock_persona_factory,
        hitl_gateway=mock_hitl_gateway,
        checkpointer=None,
    )

    assert graph is not None


# ============================================
# Graph 节点逻辑测试 (通过 mock LLM 响应)
# ============================================

@pytest.mark.asyncio
async def test_boss_graph_planning_phase(mock_persona_factory, mock_hitl_gateway):
    """测试 Boss Graph 的 planning 阶段 (简化版 - 仅测试 graph 构建)"""
    # boss.py 中 model_router 是通过 persona_factory.model_router 访问的
    # 完整的集成测试需要真实的 LLM 调用，这里只测试 graph 构建成功
    mock_model_router = MagicMock()
    mock_persona_factory.model_router = mock_model_router

    graph = build_boss_graph(
        persona_factory=mock_persona_factory,
        hitl_gateway=mock_hitl_gateway,
        checkpointer=None,
    )

    # 验证 graph 构建成功
    assert graph is not None
    assert hasattr(graph, "ainvoke")

    # 注意: 完整的 planning 测试需要 mock LLM 响应，
    # 这超出了单元测试范围，应在集成测试中完成


def test_plan_validator_integration(mock_persona_factory):
    """测试 PlanValidator 与 Boss Graph 的集成"""
    # 测试 PlanValidator 在 build_boss_graph 中被正确初始化
    mock_model_router = MagicMock()
    mock_persona_factory.model_router = mock_model_router
    mock_hitl_gateway = MagicMock(spec=HiTLGateway)

    graph = build_boss_graph(
        persona_factory=mock_persona_factory,
        hitl_gateway=mock_hitl_gateway,
        checkpointer=None,
    )

    # 验证 graph 构建时使用了 available_personas
    assert graph is not None
    mock_persona_factory.list_personas.assert_called()


def test_task_plan_get_ready_tasks():
    """测试 TaskPlan.get_ready_tasks() 逻辑"""
    tasks = [
        Task(
            task_id="t1",
            title="任务1",
            description="无依赖",
            assigned_persona="researcher",
            task_type="research",
            dependencies=[],
            status=TaskStatus.PENDING,
        ),
        Task(
            task_id="t2",
            title="任务2",
            description="依赖t1",
            assigned_persona="writer",
            task_type="writing",
            dependencies=["t1"],
            status=TaskStatus.PENDING,
        ),
    ]

    plan = TaskPlan(
        plan_id="plan_test",
        user_intent="测试",
        tasks=tasks,
    )

    # 初始状态: 只有 t1 ready (completed_ids 为空)
    ready = plan.get_ready_tasks(completed_ids=set())
    assert len(ready) == 1
    assert ready[0].task_id == "t1"

    # t1 完成后: t2 ready
    tasks[0].status = TaskStatus.COMPLETED
    ready = plan.get_ready_tasks(completed_ids={"t1"})
    assert len(ready) == 1
    assert ready[0].task_id == "t2"

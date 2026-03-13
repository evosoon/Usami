"""
Usami — PlanValidator 单元测试
"""

from __future__ import annotations

import pytest
from core.state import TaskPlan, Task
from core.plan_validator import PlanValidator


# ============================================
# validate() — 正常场景
# ============================================

class TestPlanValidatorValid:
    """合法计划通过验证"""

    def test_simple_linear_plan(self, validator, simple_plan):
        is_valid, errors = validator.validate(simple_plan)
        assert is_valid is True
        assert errors == []

    def test_single_task_no_deps(self, validator):
        plan = TaskPlan(
            plan_id="p1",
            user_intent="test",
            tasks=[
                Task(
                    task_id="t1",
                    title="Research",
                    description="do research",
                    assigned_persona="researcher",
                    task_type="research",
                ),
            ],
        )
        is_valid, errors = validator.validate(plan)
        assert is_valid is True
        assert errors == []

    def test_diamond_dag(self, validator):
        """菱形 DAG: t1 → t2, t3 → t4"""
        plan = TaskPlan(
            plan_id="p_diamond",
            user_intent="test",
            tasks=[
                Task(task_id="t1", title="A", description="a",
                     assigned_persona="researcher", task_type="research"),
                Task(task_id="t2", title="B", description="b",
                     assigned_persona="writer", task_type="writing",
                     dependencies=["t1"]),
                Task(task_id="t3", title="C", description="c",
                     assigned_persona="analyst", task_type="analysis",
                     dependencies=["t1"]),
                Task(task_id="t4", title="D", description="d",
                     assigned_persona="writer", task_type="writing",
                     dependencies=["t2", "t3"]),
            ],
        )
        is_valid, errors = validator.validate(plan)
        assert is_valid is True
        assert errors == []


# ============================================
# validate() — 错误场景
# ============================================

class TestPlanValidatorErrors:
    """各种非法计划的检测"""

    def test_empty_plan(self, validator):
        plan = TaskPlan(plan_id="p_empty", user_intent="test", tasks=[])
        is_valid, errors = validator.validate(plan)
        assert is_valid is False
        assert any("任务计划为空" in e for e in errors)

    def test_duplicate_task_ids(self, validator):
        plan = TaskPlan(
            plan_id="p_dup",
            user_intent="test",
            tasks=[
                Task(task_id="t1", title="A", description="a",
                     assigned_persona="researcher", task_type="research"),
                Task(task_id="t1", title="B", description="b",
                     assigned_persona="writer", task_type="writing"),
            ],
        )
        is_valid, errors = validator.validate(plan)
        assert is_valid is False
        assert any("重复的任务 ID" in e for e in errors)

    def test_unknown_persona(self, validator):
        plan = TaskPlan(
            plan_id="p_persona",
            user_intent="test",
            tasks=[
                Task(task_id="t1", title="A", description="a",
                     assigned_persona="nonexistent_persona", task_type="research"),
            ],
        )
        is_valid, errors = validator.validate(plan)
        assert is_valid is False
        assert any("不存在的 Persona" in e for e in errors)

    def test_invalid_dependency_reference(self, validator):
        plan = TaskPlan(
            plan_id="p_dep",
            user_intent="test",
            tasks=[
                Task(task_id="t1", title="A", description="a",
                     assigned_persona="researcher", task_type="research",
                     dependencies=["t_nonexistent"]),
            ],
        )
        is_valid, errors = validator.validate(plan)
        assert is_valid is False
        assert any("不存在的任务" in e for e in errors)

    def test_cycle_detection(self, validator):
        """A → B → A 循环"""
        plan = TaskPlan(
            plan_id="p_cycle",
            user_intent="test",
            tasks=[
                Task(task_id="t1", title="A", description="a",
                     assigned_persona="researcher", task_type="research",
                     dependencies=["t2"]),
                Task(task_id="t2", title="B", description="b",
                     assigned_persona="writer", task_type="writing",
                     dependencies=["t1"]),
            ],
        )
        is_valid, errors = validator.validate(plan)
        assert is_valid is False
        assert any("循环依赖" in e for e in errors)

    def test_self_dependency(self, validator):
        plan = TaskPlan(
            plan_id="p_self",
            user_intent="test",
            tasks=[
                Task(task_id="t1", title="A", description="a",
                     assigned_persona="researcher", task_type="research",
                     dependencies=["t1"]),
            ],
        )
        is_valid, errors = validator.validate(plan)
        assert is_valid is False
        assert any("循环依赖" in e for e in errors)


# ============================================
# should_require_hitl_preview()
# ============================================

class TestHiTLPreview:
    """计划复杂度 → 是否需要人类预览"""

    def test_simple_plan_no_preview(self, validator, simple_plan):
        """2 个任务、1 层深度 → 不需要预览"""
        assert validator.should_require_hitl_preview(simple_plan) is False

    def test_many_tasks_triggers_preview(self, validator):
        """6 个任务 → 需要预览 (>5)"""
        tasks = [
            Task(
                task_id=f"t{i}",
                title=f"Task {i}",
                description="d",
                assigned_persona="researcher",
                task_type="research",
            )
            for i in range(6)
        ]
        plan = TaskPlan(plan_id="p_many", user_intent="test", tasks=tasks)
        assert validator.should_require_hitl_preview(plan) is True

    def test_deep_chain_triggers_preview(self, validator):
        """4 层依赖链: t1 → t2 → t3 → t4 → t5 (depth=4 > 3)"""
        tasks = [
            Task(task_id="t1", title="T1", description="d",
                 assigned_persona="researcher", task_type="research"),
            Task(task_id="t2", title="T2", description="d",
                 assigned_persona="researcher", task_type="research",
                 dependencies=["t1"]),
            Task(task_id="t3", title="T3", description="d",
                 assigned_persona="writer", task_type="writing",
                 dependencies=["t2"]),
            Task(task_id="t4", title="T4", description="d",
                 assigned_persona="analyst", task_type="analysis",
                 dependencies=["t3"]),
            Task(task_id="t5", title="T5", description="d",
                 assigned_persona="writer", task_type="writing",
                 dependencies=["t4"]),
        ]
        plan = TaskPlan(plan_id="p_deep", user_intent="test", tasks=tasks)
        assert validator.should_require_hitl_preview(plan) is True

    def test_five_tasks_shallow_no_preview(self, validator):
        """5 个任务 (≤5) + 深度 1 → 不触发预览"""
        tasks = [
            Task(task_id="t0", title="root", description="d",
                 assigned_persona="researcher", task_type="research"),
        ] + [
            Task(
                task_id=f"t{i}",
                title=f"Task {i}",
                description="d",
                assigned_persona="writer",
                task_type="writing",
                dependencies=["t0"],
            )
            for i in range(1, 5)
        ]
        plan = TaskPlan(plan_id="p_5", user_intent="test", tasks=tasks)
        assert validator.should_require_hitl_preview(plan) is False

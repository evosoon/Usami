"""
Usami — State Schema 单元测试
重点: TaskPlan.get_ready_tasks() 逻辑
"""

from __future__ import annotations

from core.state import Task, TaskOutput, TaskPlan, TaskStatus

# ============================================
# get_ready_tasks()
# ============================================

class TestGetReadyTasks:

    def test_no_deps_all_ready(self):
        """无依赖的任务全部就绪"""
        plan = TaskPlan(
            plan_id="p1",
            user_intent="test",
            tasks=[
                Task(task_id="t1", title="A", description="a",
                     assigned_persona="researcher", task_type="research"),
                Task(task_id="t2", title="B", description="b",
                     assigned_persona="writer", task_type="writing"),
            ],
        )
        ready = plan.get_ready_tasks(completed_ids=set())
        assert len(ready) == 2
        assert {t.task_id for t in ready} == {"t1", "t2"}

    def test_deps_block_task(self):
        """有依赖且依赖未完成 → 被阻塞"""
        plan = TaskPlan(
            plan_id="p2",
            user_intent="test",
            tasks=[
                Task(task_id="t1", title="A", description="a",
                     assigned_persona="researcher", task_type="research"),
                Task(task_id="t2", title="B", description="b",
                     assigned_persona="writer", task_type="writing",
                     dependencies=["t1"]),
            ],
        )
        ready = plan.get_ready_tasks(completed_ids=set())
        assert len(ready) == 1
        assert ready[0].task_id == "t1"

    def test_deps_satisfied_unlocks_task(self):
        """依赖完成后解锁下游任务"""
        plan = TaskPlan(
            plan_id="p3",
            user_intent="test",
            tasks=[
                Task(task_id="t1", title="A", description="a",
                     assigned_persona="researcher", task_type="research",
                     status=TaskStatus.COMPLETED),
                Task(task_id="t2", title="B", description="b",
                     assigned_persona="writer", task_type="writing",
                     dependencies=["t1"]),
            ],
        )
        ready = plan.get_ready_tasks(completed_ids={"t1"})
        assert len(ready) == 1
        assert ready[0].task_id == "t2"

    def test_completed_task_not_returned(self):
        """已完成的任务不会被重复返回"""
        plan = TaskPlan(
            plan_id="p4",
            user_intent="test",
            tasks=[
                Task(task_id="t1", title="A", description="a",
                     assigned_persona="researcher", task_type="research",
                     status=TaskStatus.COMPLETED),
            ],
        )
        ready = plan.get_ready_tasks(completed_ids={"t1"})
        assert ready == []

    def test_running_task_tracked_by_completed_ids(self):
        """v2: get_ready_tasks uses completed_ids, not task.status

        Tasks are tracked by completed_ids (append-only reducer),
        not by task.status field. Running tasks should be in completed_ids.
        """
        plan = TaskPlan(
            plan_id="p5",
            user_intent="test",
            tasks=[
                Task(task_id="t1", title="A", description="a",
                     assigned_persona="researcher", task_type="research",
                     status=TaskStatus.RUNNING),  # status field is informational
            ],
        )
        # With empty completed_ids, task is returned (even if status=RUNNING)
        ready = plan.get_ready_tasks(completed_ids=set())
        assert len(ready) == 1

        # When task_id is in completed_ids, task is filtered out
        ready = plan.get_ready_tasks(completed_ids={"t1"})
        assert ready == []

    def test_all_completed_returns_empty(self):
        """所有任务完成 → 空列表"""
        plan = TaskPlan(
            plan_id="p6",
            user_intent="test",
            tasks=[
                Task(task_id="t1", title="A", description="a",
                     assigned_persona="researcher", task_type="research",
                     status=TaskStatus.COMPLETED),
                Task(task_id="t2", title="B", description="b",
                     assigned_persona="writer", task_type="writing",
                     status=TaskStatus.COMPLETED,
                     dependencies=["t1"]),
            ],
        )
        ready = plan.get_ready_tasks(completed_ids={"t1", "t2"})
        assert ready == []

    def test_partial_deps_still_blocked(self):
        """多个依赖只完成部分 → 仍阻塞"""
        plan = TaskPlan(
            plan_id="p7",
            user_intent="test",
            tasks=[
                Task(task_id="t1", title="A", description="a",
                     assigned_persona="researcher", task_type="research",
                     status=TaskStatus.COMPLETED),
                Task(task_id="t2", title="B", description="b",
                     assigned_persona="analyst", task_type="analysis"),
                Task(task_id="t3", title="C", description="c",
                     assigned_persona="writer", task_type="writing",
                     dependencies=["t1", "t2"]),
            ],
        )
        ready = plan.get_ready_tasks(completed_ids={"t1"})
        # t2 就绪 (无依赖 + PENDING), t3 阻塞 (t2 未完成)
        assert len(ready) == 1
        assert ready[0].task_id == "t2"


# ============================================
# Pydantic Model 构造
# ============================================

class TestStateModels:

    def test_task_defaults(self):
        t = Task(
            task_id="t1",
            title="Test",
            description="desc",
            assigned_persona="researcher",
            task_type="research",
        )
        assert t.status == TaskStatus.PENDING
        assert t.dependencies == []
        assert t.priority == 0

    def test_task_output_defaults(self):
        o = TaskOutput(
            task_id="t1",
            persona="researcher",
            summary="s",
            full_result="f",
        )
        assert o.confidence == 1.0
        assert o.artifacts == []
        assert o.metadata == {}

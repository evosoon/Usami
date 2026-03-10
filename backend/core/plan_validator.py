"""
AgenticOS — Plan Validator
Pre-mortem F2 修正: Boss 生成 Plan 后，确定性代码做正确性验证

设计原则:
- LLM 做创造性决策，确定性代码做正确性验证
- 职责边界清晰
"""

from __future__ import annotations

import structlog
from core.state import TaskPlan, Task

logger = structlog.get_logger()


class PlanValidator:
    """
    任务计划验证器 — 确定性校验 Boss 的推理输出
    
    检查项:
    1. DAG 无循环依赖
    2. 目标 Persona 存在
    3. 任务 ID 唯一
    4. 依赖引用合法
    5. 预估复杂度 → 是否需要 HiTL 预览
    """

    def __init__(self, available_personas: list[str]):
        self._available_personas = set(available_personas)

    def validate(self, plan: TaskPlan) -> tuple[bool, list[str]]:
        """
        验证任务计划
        
        Returns:
            (is_valid, error_messages)
        """
        errors: list[str] = []

        # Check 1: 任务列表非空
        if not plan.tasks:
            errors.append("任务计划为空")
            return False, errors

        # Check 2: 任务 ID 唯一
        task_ids = [t.task_id for t in plan.tasks]
        if len(task_ids) != len(set(task_ids)):
            duplicates = [tid for tid in task_ids if task_ids.count(tid) > 1]
            errors.append(f"存在重复的任务 ID: {set(duplicates)}")

        # Check 3: 目标 Persona 存在
        for task in plan.tasks:
            if task.assigned_persona not in self._available_personas:
                errors.append(
                    f"任务 [{task.task_id}] 分配给不存在的 Persona: "
                    f"'{task.assigned_persona}' "
                    f"(可用: {self._available_personas})"
                )

        # Check 4: 依赖引用合法
        task_id_set = set(task_ids)
        for task in plan.tasks:
            for dep in task.dependencies:
                if dep not in task_id_set:
                    errors.append(
                        f"任务 [{task.task_id}] 依赖不存在的任务: '{dep}'"
                    )

        # Check 5: DAG 无循环依赖
        if not errors:  # 只有前面没错时才检查循环
            cycle = self._detect_cycle(plan.tasks)
            if cycle:
                errors.append(f"检测到循环依赖: {' → '.join(cycle)}")

        is_valid = len(errors) == 0

        if not is_valid:
            logger.warning("plan_validation_failed", errors=errors)
        else:
            logger.info("plan_validation_passed", task_count=len(plan.tasks))

        return is_valid, errors

    def should_require_hitl_preview(self, plan: TaskPlan) -> bool:
        """
        判断计划是否足够复杂，需要人类预览
        
        规则:
        - 任务数 > 5 → 建议预览
        - 存在 3 层以上依赖链 → 建议预览
        """
        if len(plan.tasks) > 5:
            return True
        
        # 检查最长依赖链深度
        max_depth = self._max_dependency_depth(plan.tasks)
        if max_depth > 3:
            return True
        
        return False

    def _detect_cycle(self, tasks: list[Task]) -> list[str] | None:
        """拓扑排序检测循环依赖"""
        graph: dict[str, list[str]] = {t.task_id: t.dependencies for t in tasks}
        visited: set[str] = set()
        rec_stack: set[str] = set()
        path: list[str] = []

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    path.append(neighbor)
                    return True

            path.pop()
            rec_stack.discard(node)
            return False

        for task_id in graph:
            if task_id not in visited:
                if dfs(task_id):
                    # 提取循环部分
                    cycle_start = path[-1]
                    cycle_idx = path.index(cycle_start)
                    return path[cycle_idx:]
        
        return None

    def _max_dependency_depth(self, tasks: list[Task]) -> int:
        """计算最长依赖链深度"""
        dep_map = {t.task_id: t.dependencies for t in tasks}
        cache: dict[str, int] = {}

        def depth(tid: str) -> int:
            if tid in cache:
                return cache[tid]
            deps = dep_map.get(tid, [])
            if not deps:
                cache[tid] = 0
                return 0
            d = 1 + max(depth(d) for d in deps)
            cache[tid] = d
            return d

        return max((depth(t.task_id) for t in tasks), default=0)

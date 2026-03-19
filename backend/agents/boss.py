"""
Usami — Boss Persona (Supervisor Agent)
v2 Refactor: 5-node topology with interrupt isolation

设计原则:
- 图拓扑本身就是 phase，不再手动跟踪 current_phase
- interrupt() 管理 HiTL，不再手动管理 hitl_pending
- 使用 get_stream_writer() 替代 emit() 闭包
- review 节点是 interrupt 隔离层，确保 execute 结果已持久化后再触发 HiTL

图结构:
    START → plan → validate → execute → review → route_after_review
                                ↑                    │
                                └────────────────────┘  (还有 ready tasks)
                                                     │
                                                aggregate → END
"""

from __future__ import annotations

import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph

from agents.nodes import (
    aggregate_node,
    execute_node,
    planning_node,
    review_node,
    validate_node,
)
from core.persona_factory import PersonaFactory
from core.plan_validator import PlanValidator
from core.state import BossState

logger = structlog.get_logger()


# ============================================
# Route Function (Pure Function — Only Looks at Data)
# ============================================

def route_after_review(state: BossState) -> str:
    """
    纯函数路由 — 只看数据，不看 phase 标志

    根据 task_plan 和 completed_task_ids 决定:
    - "continue": 还有 ready tasks，回到 execute
    - "aggregate": 全部完成，进入汇总
    """
    plan = state.get("task_plan")

    # 如果计划被取消或不存在，直接汇总
    if plan is None:
        return "aggregate"

    # 如果 final_result 已设置（interrupt 返回取消等），直接结束
    if state.get("final_result") is not None:
        return "aggregate"

    # 检查是否还有 ready tasks
    completed = set(state.get("completed_task_ids", []))

    # 兼容 dict 和 Pydantic 对象
    if hasattr(plan, "get_ready_tasks"):
        ready = plan.get_ready_tasks(completed)
    else:
        # plan 是 dict（checkpoint 反序列化）
        tasks = plan.get("tasks", [])
        ready = [
            t for t in tasks
            if t.get("task_id") not in completed  # 未完成
            and all(dep in completed for dep in t.get("dependencies", []))  # 依赖已满足
        ]

    return "continue" if ready else "aggregate"


# ============================================
# Boss Graph Builder (v2 — 5 Node Topology)
# ============================================

def build_boss_graph(
    persona_factory: PersonaFactory,
    checkpointer: AsyncPostgresSaver | None = None,
) -> StateGraph:
    """
    Build Boss Supervisor Graph (v2 refactor)

    5-node topology:
    - plan: 理解意图，生成任务计划
    - validate: 确定性校验 + 可选 HiTL 预览
    - execute: 并行执行 DAG 任务（不含 interrupt）
    - review: interrupt 隔离层，检查执行结果
    - aggregate: 汇总所有结果生成最终报告

    Key changes from v1:
    - No emit() closure — use get_stream_writer()
    - No current_phase — graph topology IS the phase
    - No hitl_pending — interrupt() manages HiTL
    - review node isolates interrupts from asyncio.gather
    """

    available_personas = persona_factory.list_personas()
    validator = PlanValidator(available_personas=list(available_personas.keys()))

    # 将依赖注入到 state 的 configurable 中
    # 这样节点函数可以通过 config 获取依赖
    def inject_deps(config: dict) -> dict:
        """Inject dependencies into config for node access"""
        config = config or {}
        configurable = config.get("configurable", {})
        configurable["persona_factory"] = persona_factory
        configurable["validator"] = validator
        configurable["available_personas"] = available_personas
        config["configurable"] = configurable
        return config

    # --- Build Graph ---
    graph = StateGraph(BossState)

    # --- Add Nodes ---
    graph.add_node("plan", planning_node)
    graph.add_node("validate", validate_node)
    graph.add_node("execute", execute_node)
    graph.add_node("review", review_node)
    graph.add_node("aggregate", aggregate_node)

    # --- Add Edges ---
    # 线性流程: START → plan → validate → execute → review
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "validate")
    graph.add_edge("validate", "execute")
    graph.add_edge("execute", "review")

    # 条件路由: review → execute (有 ready tasks) 或 → aggregate (全部完成)
    graph.add_conditional_edges("review", route_after_review, {
        "continue": "execute",
        "aggregate": "aggregate",
    })

    # 终点: aggregate → END
    graph.add_edge("aggregate", END)

    return graph.compile(checkpointer=checkpointer)

"""
AgenticOS — Boss Persona (Supervisor Agent)
核心编排者: 意图理解 → 任务分解 → DAG 调度 → 汇总交付

Pre-mortem 修正已融入:
- F1: 通过 protocols.py 抽象，不直接暴露 LangGraph API 到业务层
- F2: Plan Validator 校验 Boss 的输出
- F3: 结构化消息传递（信封模式）
"""

from __future__ import annotations

import json
import uuid
import structlog
from typing import Any, Callable, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt

from core.state import (
    AgentState,
    TaskPlan,
    Task,
    TaskStatus,
    TaskOutput,
    HiTLType,
)
from core.plan_validator import PlanValidator
from core.hitl import HiTLGateway
from core.persona_factory import PersonaFactory
from agents.prompts import BOSS_PLANNING_PROMPT, BOSS_AGGREGATION_PROMPT

logger = structlog.get_logger()


def _get(obj: Any, key: str, default: str = "") -> str:
    """兼容 dict 和 Pydantic 对象的属性访问 (checkpoint 反序列化兼容)"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ============================================
# Boss Graph Builder
# ============================================

def build_boss_graph(
    persona_factory: PersonaFactory,
    hitl_gateway: HiTLGateway,
    checkpointer=None,
    on_event: Callable | None = None,
) -> StateGraph:
    """
    构建 Boss Supervisor Graph

    流程:
    init → planning → validate → [hitl_preview] → execute → aggregate → done
    """

    available_personas = persona_factory.list_personas()
    validator = PlanValidator(available_personas=list(available_personas.keys()))

    async def emit(event_type: str, data: dict) -> None:
        """发射事件到 WebSocket (如果 on_event 回调已注册)"""
        if on_event:
            try:
                await on_event(event_type, data)
            except Exception as e:
                logger.warning("event_emit_failed", event_type=event_type, error=str(e))

    # --- Node: Planning (Boss 分解任务) ---
    async def planning_node(state: dict) -> dict:
        """Boss 理解意图，生成任务计划"""
        user_intent = state.get("user_intent", "")
        thread_id = state.get("thread_id", "")

        await emit("task.planning", {"thread_id": thread_id})

        # 构建 Persona 列表描述
        persona_list = "\n".join(
            f"- {name}: {info['description']} (工具: {info['tools']})"
            for name, info in available_personas.items()
            if info["role"] != "orchestrator"
        )

        prompt = BOSS_PLANNING_PROMPT.format(
            user_intent=user_intent,
            persona_list=persona_list,
        )

        boss_model = persona_factory.model_router.get_model("planning")
        model_router = persona_factory.model_router
        response = await model_router.ainvoke_with_retry(boss_model, [
            SystemMessage(content="你是一个精确的任务规划者。始终输出有效的 JSON。"),
            HumanMessage(content=prompt),
        ])

        # 解析 Boss 输出为 TaskPlan
        try:
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            plan_data = json.loads(content.strip())
            task_plan = TaskPlan(**plan_data)
        except Exception as e:
            logger.error("plan_parsing_failed", error=str(e))
            task_plan = TaskPlan(
                plan_id=f"plan_{uuid.uuid4().hex[:8]}",
                user_intent=user_intent,
                tasks=[
                    Task(
                        task_id="t1",
                        title="直接回答",
                        description=user_intent,
                        assigned_persona="researcher",
                        task_type="research",
                    )
                ],
            )

        logger.info("plan_generated", task_count=len(task_plan.tasks))
        await emit("task.plan_ready", {
            "thread_id": thread_id,
            "plan_id": task_plan.plan_id,
            "task_count": len(task_plan.tasks),
        })
        return {
            "task_plan": task_plan,
            "current_phase": "validating",
        }

    # --- Node: Validate (F2 修正: 确定性校验) ---
    async def validate_node(state: dict) -> dict:
        """验证 Boss 生成的计划"""
        plan = state.get("task_plan")
        if plan is None:
            return {"current_phase": "error"}

        is_valid, errors = validator.validate(plan)

        if not is_valid:
            logger.warning("plan_invalid", errors=errors)
            hitl_req = hitl_gateway._create_request(
                hitl_type=HiTLType.ERROR,
                title="任务计划验证失败",
                description=f"Boss 生成的计划存在问题: {'; '.join(errors)}",
                context={"errors": errors, "trigger": "plan_validation"},
                options=["让 Boss 重新规划", "手动修改", "取消"],
            )
            return {
                "task_plan": plan,
                "hitl_pending": [hitl_req],
                "current_phase": "hitl_waiting",
            }

        needs_preview = validator.should_require_hitl_preview(plan)
        if needs_preview:
            hitl_req = hitl_gateway.evaluate_plan(
                task_count=len(plan.tasks),
                needs_preview=True,
            )
            if hitl_req:
                return {
                    "task_plan": plan,
                    "hitl_pending": [hitl_req],
                    "current_phase": "hitl_waiting",
                }

        return {"task_plan": plan, "current_phase": "executing"}

    # --- Node: Execute (调度 Persona 执行) ---
    async def execute_node(state: dict) -> dict:
        """按 DAG 顺序调度 Persona 执行子任务"""
        plan_data = state.get("task_plan")
        # checkpoint 反序列化: set 变为 list
        completed_ids: set = set(state.get("completed_task_ids", []))
        task_outputs: dict = state.get("task_outputs", {})
        thread_id = state.get("thread_id", "")

        if plan_data is None:
            logger.error("execute_node_no_plan", state_keys=list(state.keys()))
            return {"current_phase": "error"}

        if isinstance(plan_data, dict):
            plan = TaskPlan(**plan_data)
        else:
            plan = plan_data

        ready_tasks = plan.get_ready_tasks(completed_ids)

        if not ready_tasks:
            return {"task_plan": plan, "task_outputs": task_outputs, "current_phase": "aggregating"}

        for task in ready_tasks:
            task.status = TaskStatus.RUNNING
            logger.info("task_executing", task_id=task.task_id, persona=task.assigned_persona)
            await emit("task.executing", {
                "thread_id": thread_id,
                "task_id": task.task_id,
                "persona": task.assigned_persona,
            })

            try:
                persona_agent = persona_factory.get_persona(task.assigned_persona)

                # 构建上游摘要（F3 修正: 信封模式, 兼容 dict/Pydantic）
                upstream_context = ""
                for dep_id in task.dependencies:
                    dep_output = task_outputs.get(dep_id)
                    if dep_output:
                        persona = _get(dep_output, "persona", "unknown")
                        summary = _get(dep_output, "summary", "")
                        upstream_context += f"\n--- 来自 {persona} 的结果 ---\n{summary}\n"

                persona_input = {
                    "messages": [
                        HumanMessage(content=f"""
任务: {task.title}
描述: {task.description}

{f"上游任务结果:{upstream_context}" if upstream_context else ""}

请执行此任务并输出结果。
""")
                    ]
                }

                logger.info("persona_invoking", persona=task.assigned_persona, task_id=task.task_id)
                result = await persona_agent.ainvoke(
                    persona_input,
                    config={"recursion_limit": 10},
                )
                logger.info("persona_completed", persona=task.assigned_persona, task_id=task.task_id)
                result_content = result["messages"][-1].content if result.get("messages") else ""

                summary = result_content[:500] + ("..." if len(result_content) > 500 else "")

                output = TaskOutput(
                    task_id=task.task_id,
                    persona=task.assigned_persona,
                    summary=summary,
                    full_result=result_content,
                    confidence=0.8,
                )

                task.status = TaskStatus.COMPLETED
                task_outputs[task.task_id] = output
                completed_ids.add(task.task_id)

                await emit("task.progress", {
                    "thread_id": thread_id,
                    "task_id": task.task_id,
                    "status": "completed",
                    "persona": task.assigned_persona,
                })

                hitl_req = hitl_gateway.evaluate(output)
                if hitl_req:
                    return {
                        "task_plan": plan,
                        "task_outputs": task_outputs,
                        "completed_task_ids": list(completed_ids),
                        "hitl_pending": [hitl_req],
                        "current_phase": "hitl_waiting",
                    }

            except Exception as e:
                logger.error("task_execution_failed", task_id=task.task_id, error=str(e))
                task.status = TaskStatus.FAILED
                output = TaskOutput(
                    task_id=task.task_id,
                    persona=task.assigned_persona,
                    summary=f"执行失败: {str(e)}",
                    full_result=str(e),
                    confidence=0.0,
                    metadata={"error": str(e)},
                )
                task_outputs[task.task_id] = output

                await emit("task.failed", {
                    "thread_id": thread_id,
                    "task_id": task.task_id,
                    "error": str(e),
                })

                hitl_req = hitl_gateway.evaluate(output, retry_count=3)
                if hitl_req:
                    return {
                        "task_plan": plan,
                        "task_outputs": task_outputs,
                        "completed_task_ids": list(completed_ids),
                        "hitl_pending": [hitl_req],
                        "current_phase": "hitl_waiting",
                    }

        new_ready = plan.get_ready_tasks(completed_ids)
        next_phase = "executing" if new_ready else "aggregating"

        return {
            "task_plan": plan,
            "task_outputs": task_outputs,
            "completed_task_ids": list(completed_ids),
            "current_phase": next_phase,
        }

    # --- Node: Aggregate (Boss 汇总结果) ---
    async def aggregate_node(state: dict) -> dict:
        """Boss 汇总所有 Persona 的结果，生成最终交付物"""
        user_intent = state.get("user_intent", "")
        task_outputs: dict = state.get("task_outputs", {})
        thread_id = state.get("thread_id", "")

        # 构建摘要列表（兼容 dict/Pydantic）
        task_summaries = "\n".join(
            f"[{tid}] ({_get(output, 'persona', 'unknown')}): {_get(output, 'summary', '')}"
            for tid, output in task_outputs.items()
        )

        prompt = BOSS_AGGREGATION_PROMPT.format(
            user_intent=user_intent,
            task_summaries=task_summaries,
        )

        boss_model = persona_factory.model_router.get_model("writing")
        model_router = persona_factory.model_router
        response = await model_router.ainvoke_with_retry(boss_model, [
            SystemMessage(content="你是一个专业的内容汇总者。输出结构清晰的最终报告。"),
            HumanMessage(content=prompt),
        ])

        final_output = TaskOutput(
            task_id="final",
            persona="boss",
            summary="最终报告已生成",
            full_result=response.content,
            confidence=1.0,
        )

        task_outputs["final"] = final_output
        await emit("task.completed", {"thread_id": thread_id})
        return {
            "task_outputs": task_outputs,
            "current_phase": "done",
        }

    # --- Router: 决定下一步 ---
    def route_next(state: dict) -> str:
        """根据当前阶段路由到下一个节点"""
        phase = state.get("current_phase", "init")

        route_map = {
            "init": "planning",
            "planning": "planning",
            "validating": "validate",
            "executing": "execute",
            "hitl_waiting": END,
            "aggregating": "aggregate",
            "done": END,
            "error": END,
        }
        return route_map.get(phase, END)

    # --- Build Graph ---
    graph = StateGraph(dict)

    graph.add_node("planning", planning_node)
    graph.add_node("validate", validate_node)
    graph.add_node("execute", execute_node)
    graph.add_node("aggregate", aggregate_node)

    graph.add_edge(START, "planning")
    graph.add_edge("planning", "validate")
    graph.add_conditional_edges("validate", route_next)
    graph.add_conditional_edges("execute", route_next)
    graph.add_edge("aggregate", END)

    return graph.compile(checkpointer=checkpointer)

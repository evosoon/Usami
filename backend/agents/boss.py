"""
Usami — Boss Persona (Supervisor Agent)
Core orchestrator: intent understanding -> task decomposition -> DAG scheduling -> aggregation

Pre-mortem fixes incorporated:
- F1: Abstracted via protocols.py, LangGraph API not exposed to business layer
- F2: Plan Validator validates Boss output
- F3: Structured message passing (envelope pattern)
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from agents.prompts import (
    AGGREGATION_SYSTEM_MESSAGE,
    BOSS_AGGREGATION_PROMPT,
    BOSS_PLANNING_PROMPT,
    FALLBACK_TASK_TITLE,
    FINAL_REPORT_SUMMARY,
    HITL_PLAN_VALIDATION_DESC,
    HITL_PLAN_VALIDATION_OPTIONS,
    HITL_PLAN_VALIDATION_TITLE,
    PERSONA_LIST_LINE,
    PLANNING_SYSTEM_MESSAGE,
    TASK_EXECUTION_FAILED_SUMMARY,
    TASK_EXECUTION_TEMPLATE,
    UPSTREAM_CONTEXT_HEADER,
    UPSTREAM_RESULT_BLOCK,
)
from core.hitl import HiTLGateway
from core.persona_factory import PersonaFactory
from core.plan_validator import PlanValidator
from core.state import (
    HiTLType,
    Task,
    TaskOutput,
    TaskPlan,
    TaskStatus,
)

logger = structlog.get_logger()


def _get(obj: Any, key: str, default: str = "") -> str:
    """Attribute access compatible with both dict and Pydantic (checkpoint deserialization)"""
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
    Build Boss Supervisor Graph

    Flow:
    init -> planning -> validate -> [hitl_preview] -> execute -> aggregate -> done
    """

    available_personas = persona_factory.list_personas()
    validator = PlanValidator(available_personas=list(available_personas.keys()))

    async def emit(event_type: str, data: dict) -> None:
        """Emit event to WebSocket (if on_event callback is registered)"""
        if on_event:
            try:
                await on_event(event_type, data)
            except Exception as e:
                logger.warning("event_emit_failed", event_type=event_type, error=str(e))

    # --- Node: Planning ---
    async def planning_node(state: dict) -> dict:
        """Boss understands intent, generates task plan"""
        user_intent = state.get("user_intent", "")
        thread_id = state.get("thread_id", "")

        await emit("task.planning", {"thread_id": thread_id})

        # Build persona list description
        persona_list = "\n".join(
            PERSONA_LIST_LINE.format(
                name=name, description=info["description"], tools=info["tools"]
            )
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
            SystemMessage(content=PLANNING_SYSTEM_MESSAGE),
            HumanMessage(content=prompt),
        ])

        # Parse Boss output into TaskPlan
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
                        title=FALLBACK_TASK_TITLE,
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

    # --- Node: Validate (F2: deterministic validation) ---
    async def validate_node(state: dict) -> dict:
        """Validate the plan generated by Boss"""
        plan = state.get("task_plan")
        thread_id = state.get("thread_id", "")

        if plan is None:
            await emit("task.failed", {"thread_id": thread_id, "task_id": "validate", "error": "Plan is None"})
            return {"current_phase": "error"}

        is_valid, errors = validator.validate(plan)

        if not is_valid:
            logger.warning("plan_invalid", errors=errors)
            hitl_req = hitl_gateway._create_request(
                hitl_type=HiTLType.ERROR,
                title=HITL_PLAN_VALIDATION_TITLE,
                description=HITL_PLAN_VALIDATION_DESC.format(
                    errors="; ".join(errors)
                ),
                context={"errors": errors, "trigger": "plan_validation"},
                options=HITL_PLAN_VALIDATION_OPTIONS,
            )
            await emit("hitl.request", {
                "thread_id": thread_id,
                "request": hitl_req.model_dump(),
            })
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
                await emit("hitl.request", {
                    "thread_id": thread_id,
                    "request": hitl_req.model_dump(),
                })
                return {
                    "task_plan": plan,
                    "hitl_pending": [hitl_req],
                    "current_phase": "hitl_waiting",
                }

        return {"task_plan": plan, "current_phase": "executing"}

    # --- Node: Execute (schedule Persona execution) ---
    async def execute_node(state: dict) -> dict:
        """Schedule Persona execution in DAG order — parallel for independent tasks"""
        plan_data = state.get("task_plan")
        # Checkpoint deserialization: set becomes list
        completed_ids: set = set(state.get("completed_task_ids", []))
        task_outputs: dict = state.get("task_outputs", {})
        thread_id = state.get("thread_id", "")

        if plan_data is None:
            logger.error("execute_node_no_plan", state_keys=list(state.keys()))
            return {"current_phase": "error"}

        plan = TaskPlan(**plan_data) if isinstance(plan_data, dict) else plan_data

        ready_tasks = plan.get_ready_tasks(completed_ids)

        if not ready_tasks:
            return {"task_plan": plan, "task_outputs": task_outputs, "current_phase": "aggregating"}

        async def _run_single_task(task: Task) -> tuple[Task, TaskOutput | None, object | None]:
            """Execute a single persona task. Returns (task, output, hitl_req)."""
            task.status = TaskStatus.RUNNING
            logger.info("task_executing", task_id=task.task_id, persona=task.assigned_persona)
            await emit("task.executing", {
                "thread_id": thread_id,
                "task_id": task.task_id,
                "persona": task.assigned_persona,
            })

            try:
                persona_agent = persona_factory.get_persona(task.assigned_persona)

                # Build upstream summary (F3: envelope pattern, dict/Pydantic compatible)
                upstream_context = ""
                for dep_id in task.dependencies:
                    dep_output = task_outputs.get(dep_id)
                    if dep_output:
                        p = _get(dep_output, "persona", "unknown")
                        s = _get(dep_output, "summary", "")
                        upstream_context += UPSTREAM_RESULT_BLOCK.format(
                            persona=p, summary=s
                        )

                upstream_section = (
                    UPSTREAM_CONTEXT_HEADER.format(upstream_context=upstream_context)
                    if upstream_context else ""
                )

                persona_input = {
                    "messages": [
                        HumanMessage(content=TASK_EXECUTION_TEMPLATE.format(
                            title=task.title,
                            description=task.description,
                            upstream_section=upstream_section,
                        ))
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

                await emit("task.progress", {
                    "thread_id": thread_id,
                    "task_id": task.task_id,
                    "status": "completed",
                    "persona": task.assigned_persona,
                })

                hitl_req = hitl_gateway.evaluate(output)
                return task, output, hitl_req

            except Exception as e:
                logger.error("task_execution_failed", task_id=task.task_id, error=str(e))
                task.status = TaskStatus.FAILED
                output = TaskOutput(
                    task_id=task.task_id,
                    persona=task.assigned_persona,
                    summary=TASK_EXECUTION_FAILED_SUMMARY.format(error=str(e)),
                    full_result=str(e),
                    confidence=0.0,
                    metadata={"error": str(e)},
                )

                await emit("task.failed", {
                    "thread_id": thread_id,
                    "task_id": task.task_id,
                    "error": str(e),
                })

                hitl_req = hitl_gateway.evaluate(output, retry_count=3)
                return task, output, hitl_req

        # Run all ready tasks in parallel
        import asyncio
        results = await asyncio.gather(
            *[_run_single_task(t) for t in ready_tasks],
            return_exceptions=True,
        )

        # Collect results
        for res in results:
            if isinstance(res, Exception):
                logger.error("task_gather_exception", error=str(res))
                continue
            task, output, hitl_req = res
            if output:
                task_outputs[task.task_id] = output
                if task.status == TaskStatus.COMPLETED:
                    completed_ids.add(task.task_id)
            if hitl_req:
                await emit("hitl.request", {
                    "thread_id": thread_id,
                    "request": hitl_req.model_dump(),
                })
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

    # --- Node: Aggregate ---
    async def aggregate_node(state: dict) -> dict:
        """Boss aggregates all Persona results into final deliverable"""
        user_intent = state.get("user_intent", "")
        task_outputs: dict = state.get("task_outputs", {})
        thread_id = state.get("thread_id", "")

        # Single-task shortcut: skip LLM aggregation, use result directly
        non_final = {k: v for k, v in task_outputs.items() if k != "final"}
        if len(non_final) == 1:
            single_output = next(iter(non_final.values()))
            full_result = _get(single_output, "full_result", "")
            logger.info("aggregate_shortcut", thread_id=thread_id, reason="single_task")
            final_output = TaskOutput(
                task_id="final",
                persona="boss",
                summary=FINAL_REPORT_SUMMARY,
                full_result=full_result,
                confidence=1.0,
            )
            task_outputs["final"] = final_output
            await emit("task.completed", {"thread_id": thread_id, "result": full_result})
            return {"task_outputs": task_outputs, "current_phase": "done"}

        # Multi-task: LLM aggregation
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
            SystemMessage(content=AGGREGATION_SYSTEM_MESSAGE),
            HumanMessage(content=prompt),
        ])

        final_output = TaskOutput(
            task_id="final",
            persona="boss",
            summary=FINAL_REPORT_SUMMARY,
            full_result=response.content,
            confidence=1.0,
        )

        task_outputs["final"] = final_output
        await emit("task.completed", {"thread_id": thread_id, "result": final_output.full_result})
        return {
            "task_outputs": task_outputs,
            "current_phase": "done",
        }

    # --- Router ---
    def route_next(state: dict) -> str:
        """Route to next node based on current phase"""
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

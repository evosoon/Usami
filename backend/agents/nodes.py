"""
Usami — Boss Graph Nodes
Node functions for the Boss supervisor graph.
Each node receives dependencies via keyword arguments (no closures).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from agents.prompts import (
    AGGREGATION_SYSTEM_MESSAGE,
    BOSS_AGGREGATION_PROMPT,
    BOSS_PLANNING_PROMPT,
    FALLBACK_TASK_TITLE,
    FINAL_REPORT_SUMMARY,
    FOLLOW_UP_CONTEXT,
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

EmitFn = Callable[[str, dict], Any]


def _get(obj: Any, key: str, default: str = "") -> str:
    """Attribute access compatible with both dict and Pydantic (checkpoint deserialization)"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


async def _start_heartbeat(
    emit: EmitFn, thread_id: str, phase: str,
) -> asyncio.Task:
    """Start a background heartbeat task that emits periodic keep-alive events."""
    start_time = asyncio.get_event_loop().time()

    async def _beat():
        while True:
            await asyncio.sleep(8)
            elapsed = int(asyncio.get_event_loop().time() - start_time)
            await emit("task.heartbeat", {
                "thread_id": thread_id,
                "phase": phase,
                "elapsed_s": elapsed,
            })

    return asyncio.create_task(_beat())


# --- Node: Planning ---

async def planning_node(
    state: dict,
    *,
    emit: EmitFn,
    persona_factory: PersonaFactory,
    available_personas: dict,
) -> dict:
    """Boss understands intent, generates task plan (streamed)"""
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

    # Append previous result context for follow-up questions
    previous_result = state.get("previous_result")
    follow_up_section = ""
    if previous_result:
        follow_up_section = FOLLOW_UP_CONTEXT.format(
            previous_result=previous_result[:2000]
        )

    prompt = BOSS_PLANNING_PROMPT.format(
        user_intent=user_intent,
        persona_list=persona_list,
    ) + follow_up_section

    boss_model = persona_factory.model_router.get_model("planning")
    model_router = persona_factory.model_router
    messages = [
        SystemMessage(content=PLANNING_SYSTEM_MESSAGE),
        HumanMessage(content=prompt),
    ]

    full_response = ""
    heartbeat = await _start_heartbeat(emit, thread_id, "planning")
    try:
        async for chunk in model_router.astream_with_retry(boss_model, messages):
            token = chunk.content if hasattr(chunk, "content") else str(chunk)
            if token:
                full_response += token
                await emit("task.planning_chunk", {
                    "thread_id": thread_id,
                    "chunk": token,
                })
    finally:
        heartbeat.cancel()

    # Parse Boss output into TaskPlan
    try:
        content = full_response
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
        **state,
        "task_plan": task_plan,
        "current_phase": "validating",
    }


# --- Node: Validate (F2: deterministic validation) ---

async def validate_node(
    state: dict,
    *,
    emit: EmitFn,
    hitl_gateway: HiTLGateway,
    validator: PlanValidator,
) -> dict:
    """Validate the plan generated by Boss"""
    plan = state.get("task_plan")
    thread_id = state.get("thread_id", "")

    if plan is None:
        await emit("task.failed", {"thread_id": thread_id, "task_id": "validate", "error": "Plan is None"})
        return {**state, "current_phase": "error"}

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
            **state,
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
                **state,
                "task_plan": plan,
                "hitl_pending": [hitl_req],
                "current_phase": "hitl_waiting",
            }

    return {**state, "task_plan": plan, "current_phase": "executing"}


# --- Execute helper ---

async def _run_single_task(
    task: Task,
    *,
    emit: EmitFn,
    thread_id: str,
    task_outputs: dict,
    persona_factory: PersonaFactory,
    hitl_gateway: HiTLGateway,
) -> tuple[Task, TaskOutput | None, object | None]:
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
                upstream_context += UPSTREAM_RESULT_BLOCK.format(persona=p, summary=s)

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
        heartbeat = await _start_heartbeat(emit, thread_id, "executing")
        try:
            result = await persona_agent.ainvoke(
                persona_input,
                config={"recursion_limit": 10},
            )
        finally:
            heartbeat.cancel()
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

        return task, output, None


# --- Node: Execute ---

async def execute_node(
    state: dict,
    *,
    emit: EmitFn,
    persona_factory: PersonaFactory,
    hitl_gateway: HiTLGateway,
) -> dict:
    """Schedule Persona execution in DAG order — parallel for independent tasks"""
    plan_data = state.get("task_plan")
    # Checkpoint deserialization: set becomes list
    completed_ids: set = set(state.get("completed_task_ids", []))
    task_outputs: dict = state.get("task_outputs", {})
    thread_id = state.get("thread_id", "")

    if plan_data is None:
        logger.error("execute_node_no_plan", state_keys=list(state.keys()))
        return {**state, "current_phase": "error"}

    plan = TaskPlan(**plan_data) if isinstance(plan_data, dict) else plan_data
    ready_tasks = plan.get_ready_tasks(completed_ids)

    if not ready_tasks:
        return {**state, "task_plan": plan, "task_outputs": task_outputs, "current_phase": "aggregating"}

    # Run all ready tasks in parallel
    results = await asyncio.gather(
        *[
            _run_single_task(
                t, emit=emit, thread_id=thread_id, task_outputs=task_outputs,
                persona_factory=persona_factory, hitl_gateway=hitl_gateway,
            )
            for t in ready_tasks
        ],
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
                **state,
                "task_plan": plan,
                "task_outputs": task_outputs,
                "completed_task_ids": list(completed_ids),
                "hitl_pending": [hitl_req],
                "current_phase": "hitl_waiting",
            }

    new_ready = plan.get_ready_tasks(completed_ids)
    next_phase = "executing" if new_ready else "aggregating"

    return {
        **state,
        "task_plan": plan,
        "task_outputs": task_outputs,
        "completed_task_ids": list(completed_ids),
        "current_phase": next_phase,
    }


# --- Node: Aggregate ---

async def aggregate_node(
    state: dict,
    *,
    emit: EmitFn,
    persona_factory: PersonaFactory,
) -> dict:
    """Boss aggregates all Persona results into final deliverable"""
    user_intent = state.get("user_intent", "")
    task_outputs: dict = state.get("task_outputs", {})
    thread_id = state.get("thread_id", "")

    # Single-task shortcut: skip LLM aggregation, stream result directly
    non_final = {k: v for k, v in task_outputs.items() if k != "final"}
    if len(non_final) == 1:
        single_output = next(iter(non_final.values()))
        full_result = _get(single_output, "full_result", "")
        logger.info("aggregate_shortcut", thread_id=thread_id, reason="single_task")

        await emit("task.aggregating", {"thread_id": thread_id})
        # Stream the result in chunks for consistent UX
        chunk_size = 20
        for i in range(0, len(full_result), chunk_size):
            chunk = full_result[i:i + chunk_size]
            await emit("task.result_chunk", {
                "thread_id": thread_id,
                "chunk": chunk,
            })
            await asyncio.sleep(0.01)  # yield control

        final_output = TaskOutput(
            task_id="final",
            persona="boss",
            summary=FINAL_REPORT_SUMMARY,
            full_result=full_result,
            confidence=1.0,
        )
        task_outputs["final"] = final_output
        await emit("task.completed", {"thread_id": thread_id, "result": full_result})
        return {**state, "task_outputs": task_outputs, "current_phase": "done"}

    # Multi-task: LLM aggregation (streamed)
    task_summaries = "\n".join(
        f"[{tid}] ({_get(output, 'persona', 'unknown')}): {_get(output, 'summary', '')}"
        for tid, output in task_outputs.items()
    )

    prompt = BOSS_AGGREGATION_PROMPT.format(
        user_intent=user_intent,
        task_summaries=task_summaries,
    )

    await emit("task.aggregating", {"thread_id": thread_id})

    boss_model = persona_factory.model_router.get_model("writing")
    model_router = persona_factory.model_router
    messages = [
        SystemMessage(content=AGGREGATION_SYSTEM_MESSAGE),
        HumanMessage(content=prompt),
    ]

    full_result = ""
    heartbeat = await _start_heartbeat(emit, thread_id, "aggregating")
    try:
        async for chunk in model_router.astream_with_retry(boss_model, messages):
            token = chunk.content if hasattr(chunk, "content") else str(chunk)
            if token:
                full_result += token
                await emit("task.result_chunk", {
                    "thread_id": thread_id,
                    "chunk": token,
                })
    finally:
        heartbeat.cancel()

    final_output = TaskOutput(
        task_id="final",
        persona="boss",
        summary=FINAL_REPORT_SUMMARY,
        full_result=full_result,
        confidence=1.0,
    )

    task_outputs["final"] = final_output
    await emit("task.completed", {"thread_id": thread_id, "result": full_result})
    return {
        **state,
        "task_outputs": task_outputs,
        "current_phase": "done",
    }

"""
Usami — Boss Graph Nodes (v2 Refactor)
Node functions for the Boss supervisor graph.

v2 设计原则:
- 使用 get_stream_writer() 替代 emit() 闭包
- 使用 interrupt() 管理 HiTL
- execute_node 内部绝不调用 interrupt()（避免与 asyncio.gather 冲突）
- review_node 是 interrupt 隔离层
- 幂等性守卫：已完成的任务不重复执行

依赖注入:
- 通过 RunnableConfig 获取 persona_factory, validator 等依赖
- 或者通过 state 中的 thread_id 获取 context
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.config import get_stream_writer
from langgraph.types import interrupt, RunnableConfig

from agents.prompts import (
    AGGREGATION_SYSTEM_MESSAGE,
    BOSS_AGGREGATION_PROMPT,
    BOSS_PLANNING_PROMPT,
    FALLBACK_TASK_TITLE,
    FINAL_REPORT_SUMMARY,
    FOLLOW_UP_CONTEXT,
    PERSONA_LIST_LINE,
    PLANNING_SYSTEM_MESSAGE,
    TASK_EXECUTION_FAILED_SUMMARY,
    TASK_EXECUTION_TEMPLATE,
    UPSTREAM_CONTEXT_HEADER,
    UPSTREAM_RESULT_BLOCK,
)
from core.plan_validator import PlanValidator
from core.state import (
    BossState,
    Task,
    TaskOutput,
    TaskPlan,
    TaskStatus,
)

logger = structlog.get_logger()


# ============================================
# Helper Functions
# ============================================

def _truncate_summary(text: str, max_chars: int = 1000) -> str:
    """Format-safe summary truncation at paragraph/sentence boundaries.

    Targets ~500 tokens via ~1000 chars. Avoids mid-word or
    mid-markdown-structure cuts that break downstream rendering.
    """
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    # Prefer paragraph boundary
    last_para = truncated.rfind("\n\n")
    if last_para > max_chars * 0.6:
        return truncated[:last_para].rstrip() + "\n\n..."
    # Fallback: sentence/line boundary (Chinese + English punctuation)
    for sep in ("\n", "。", ". ", "；", "; "):
        pos = truncated.rfind(sep)
        if pos > max_chars * 0.6:
            return truncated[:pos + len(sep)].rstrip() + "\n\n..."
    return truncated.rstrip() + "\n\n..."


def _get(obj: Any, key: str, default: str = "") -> str:
    """Attribute access compatible with both dict and Pydantic (checkpoint deserialization)"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _get_plan(state: BossState) -> TaskPlan | None:
    """Get TaskPlan from state, handling both dict and Pydantic forms"""
    plan_data = state.get("task_plan")
    if plan_data is None:
        return None
    if isinstance(plan_data, TaskPlan):
        return plan_data
    # Checkpoint deserialization: plan is dict
    return TaskPlan(**plan_data)


def _build_upstream_context(task: Task, task_outputs: dict) -> str:
    """Build upstream context using envelope pattern (F3)"""
    upstream_context = ""
    deps = task.dependencies if hasattr(task, "dependencies") else task.get("dependencies", [])

    for dep_id in deps:
        dep_output = task_outputs.get(dep_id)
        if dep_output:
            p = _get(dep_output, "persona", "unknown")
            s = _get(dep_output, "summary", "")
            upstream_context += UPSTREAM_RESULT_BLOCK.format(persona=p, summary=s)

    if upstream_context:
        return UPSTREAM_CONTEXT_HEADER.format(upstream_context=upstream_context)
    return ""


# ============================================
# Node: Planning
# ============================================

async def planning_node(state: BossState, config: RunnableConfig) -> dict:
    """
    Boss 理解意图，生成任务计划（流式输出）

    使用 get_stream_writer() 发送自定义事件（替代 emit）
    解析失败时使用 interrupt() 让用户决定
    """
    writer = get_stream_writer()
    configurable = config.get("configurable", {})

    user_intent = state.get("user_intent", "")
    thread_id = state.get("thread_id", "")
    previous_result = state.get("previous_result")

    # 获取依赖
    persona_factory = configurable.get("persona_factory")
    available_personas = configurable.get("available_personas", {})

    # 1. 通知前端进入 planning 阶段
    writer({"type": "phase.change", "data": {
        "phase": "planning",
        "thread_id": thread_id,
    }})

    # 2. 构造 prompt
    persona_list = "\n".join(
        PERSONA_LIST_LINE.format(
            name=name, description=info["description"], tools=info["tools"]
        )
        for name, info in available_personas.items()
        if info.get("role") != "orchestrator"
    )

    # 追问上下文
    follow_up_section = ""
    if previous_result:
        follow_up_section = FOLLOW_UP_CONTEXT.format(
            previous_result=previous_result[:2000]
        )

    prompt = BOSS_PLANNING_PROMPT.format(
        user_intent=user_intent,
        persona_list=persona_list,
    ) + follow_up_section

    # 3. 调用 LLM（流式）
    boss_model = persona_factory.model_router.get_model("planning")
    model_router = persona_factory.model_router
    messages = [
        SystemMessage(content=PLANNING_SYSTEM_MESSAGE),
        HumanMessage(content=prompt),
    ]

    full_response = ""
    async for chunk in model_router.astream_with_retry(boss_model, messages):
        token = chunk.content if hasattr(chunk, "content") else str(chunk)
        if token:
            full_response += token
            # LLM token 通过 stream_mode="messages" 自动捕获
            # 这里额外发送自定义事件用于兼容
            writer({"type": "llm.token", "data": {
                "thread_id": thread_id,
                "content": token,
                "node": "plan",
            }})

    # 4. 解析 plan
    plan: TaskPlan | None = None
    try:
        content = full_response
        # Try code fence extraction first
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        try:
            plan_data = json.loads(content.strip())
        except json.JSONDecodeError:
            # Fallback: extract outermost JSON object via regex
            match = re.search(r'\{[\s\S]*\}', full_response)
            if match:
                plan_data = json.loads(match.group())
            else:
                raise

        plan = TaskPlan(**plan_data)

        # ⚠️ CRITICAL: Make task_ids unique per plan to avoid collision with completed_task_ids
        # LLM generates "t1", "t2", etc. which collide across conversation turns.
        # Prefix with plan UUID to ensure uniqueness.
        plan_uuid = plan.plan_id.replace("plan_", "")[:8]  # e.g., "a1b2c3d4"
        id_mapping: dict[str, str] = {}

        for task in plan.tasks:
            old_id = task.task_id
            new_id = f"{plan_uuid}_{old_id}"
            id_mapping[old_id] = new_id
            # Task is a Pydantic model — use model_copy for immutable update
            task.task_id = new_id

        # Update dependencies to use new task_ids
        for task in plan.tasks:
            task.dependencies = [id_mapping.get(dep, dep) for dep in task.dependencies]

        logger.info("task_ids_prefixed", plan_id=plan.plan_id, id_mapping=id_mapping)

    except Exception as e:
        logger.error("plan_parsing_failed", error=str(e))

        # interrupt 让用户决定（而非静默降级）
        # ⚠️ interrupt 前无副作用，所以重跑安全
        decision = interrupt({
            "type": "planning_failed",
            "raw_output": full_response[:2000],
            "message": "无法解析任务计划，是否使用单任务模式继续？",
            "options": ["retry", "fallback", "cancel"],
        })

        action = decision.get("action") if isinstance(decision, dict) else decision
        if action == "fallback":
            fallback_uuid = uuid.uuid4().hex[:8]
            plan = TaskPlan(
                plan_id=f"plan_{fallback_uuid}",
                user_intent=user_intent,
                tasks=[
                    Task(
                        task_id=f"{fallback_uuid}_t1",  # Unique task_id
                        title=FALLBACK_TASK_TITLE,
                        description=user_intent,
                        assigned_persona="researcher",
                        task_type="research",
                    )
                ],
            )
        elif action == "cancel":
            return {"final_result": "任务已取消", "task_plan": None}
        # "retry" → interrupt resume 后节点从头执行 → 重新调用 LLM

    if plan is None:
        # 如果还是 None（可能是 retry 场景），创建 fallback
        fallback_uuid = uuid.uuid4().hex[:8]
        plan = TaskPlan(
            plan_id=f"plan_{fallback_uuid}",
            user_intent=user_intent,
            tasks=[
                Task(
                    task_id=f"{fallback_uuid}_t1",  # Unique task_id
                    title=FALLBACK_TASK_TITLE,
                    description=user_intent,
                    assigned_persona="researcher",
                    task_type="research",
                )
            ],
        )

    # 5. 通知前端计划已就绪
    logger.info("plan_generated", task_count=len(plan.tasks))
    writer({"type": "phase.change", "data": {
        "phase": "planned",
        "thread_id": thread_id,
        "plan_id": plan.plan_id,
        "task_count": len(plan.tasks),
        "tasks": [t.model_dump() for t in plan.tasks],
    }})

    return {"task_plan": plan}


# ============================================
# Node: Validate
# ============================================

async def validate_node(state: BossState, config: RunnableConfig) -> dict:
    """
    验证 Boss 生成的计划

    纯代码校验，无 LLM（确定性 + 幂等）
    校验失败或复杂计划时使用 interrupt() 让用户审查
    """
    writer = get_stream_writer()
    configurable = config.get("configurable", {})

    plan = _get_plan(state)
    thread_id = state.get("thread_id", "")

    if plan is None:
        writer({"type": "task.failed", "data": {
            "thread_id": thread_id,
            "task_id": "validate",
            "error": "Plan is None",
        }})
        return {"final_result": "计划生成失败"}

    # 获取 validator
    validator: PlanValidator = configurable.get("validator")
    if validator is None:
        # Fallback: create validator from available_personas
        available_personas = configurable.get("available_personas", {})
        validator = PlanValidator(available_personas=list(available_personas.keys()))

    # 纯代码校验
    is_valid, errors = validator.validate(plan)

    if not is_valid:
        logger.warning("plan_invalid", errors=errors)

        # interrupt — 让用户审查
        # ⚠️ validate 是纯函数，重跑安全
        decision = interrupt({
            "type": "validation_error",
            "errors": errors,
            "plan": plan.model_dump(),
            "message": f"任务计划校验失败: {'; '.join(errors)}",
            "options": ["approve_anyway", "cancel"],
        })

        action = decision.get("action") if isinstance(decision, dict) else decision
        if action == "cancel":
            return {"final_result": "任务已取消", "task_plan": None}
        # "approve_anyway" → 继续

    # 可选：复杂计划的人工预览
    if validator.should_require_hitl_preview(plan):
        decision = interrupt({
            "type": "plan_review",
            "plan": plan.model_dump(),
            "message": f"计划包含 {len(plan.tasks)} 个任务，请确认执行",
            "options": ["approve", "cancel"],
        })

        action = decision.get("action") if isinstance(decision, dict) else decision
        if action != "approve":
            return {"final_result": "任务已取消", "task_plan": None}

    return {}  # 验证通过，不修改 state


# ============================================
# Node: Execute (纯并行，不含 interrupt)
# ============================================

async def execute_node(state: BossState, config: RunnableConfig) -> dict:
    """
    并行执行 DAG 任务

    关键设计：
    - execute 内部绝不调用 interrupt() — 避免与 asyncio.gather 冲突
    - 幂等性守卫 — 检查 existing_outputs 跳过已完成任务
    - 异常在 run_single_safe 内部处理 — 失败任务生成 confidence=0.0 的输出
    - 用 get_stream_writer() 替代 emit()
    """
    writer = get_stream_writer()
    configurable = config.get("configurable", {})

    plan = _get_plan(state)
    thread_id = state.get("thread_id", "")
    user_intent = state.get("user_intent", "")  # 获取用户原始意图

    if plan is None:
        return {}

    # Checkpoint 反序列化: set → list
    completed_ids: set = set(state.get("completed_task_ids", []))
    existing_outputs: dict = state.get("task_outputs", {})

    # 获取 ready tasks
    ready_tasks = plan.get_ready_tasks(completed_ids)

    if not ready_tasks:
        return {}  # route_after_review 会路由到 aggregate

    # 获取依赖
    persona_factory = configurable.get("persona_factory")

    writer({"type": "phase.change", "data": {
        "phase": "executing",
        "thread_id": thread_id,
        "round": len(completed_ids),
        "tasks": [t.task_id for t in ready_tasks],
        "total_completed": len(completed_ids),
        "total_tasks": len(plan.tasks),
    }})

    # --- 并行执行同一层 DAG 任务 ---
    async def run_single_safe(task: Task) -> tuple[str, TaskOutput]:
        """安全执行单个任务，异常在内部处理"""
        task_id = task.task_id

        # 幂等性：如果已有结果（resume 后重跑场景），跳过
        if task_id in existing_outputs:
            logger.info("task_skipped_existing", task_id=task_id)
            return task_id, existing_outputs[task_id]

        writer({"type": "task.executing", "data": {
            "thread_id": thread_id,
            "task_id": task_id,
            "persona": task.assigned_persona,
        }})

        try:
            persona_agent = persona_factory.get_persona(task.assigned_persona)

            # 构建上游上下文（信封模式 F3）
            upstream_section = _build_upstream_context(task, existing_outputs)

            persona_input = {
                "messages": [
                    HumanMessage(content=TASK_EXECUTION_TEMPLATE.format(
                        user_intent=user_intent,  # 传递用户原始意图
                        title=task.title,
                        description=task.description,
                        upstream_section=upstream_section,
                    ))
                ]
            }

            logger.info("persona_invoking", persona=task.assigned_persona, task_id=task_id)
            result = await persona_agent.ainvoke(
                persona_input,
                config={"recursion_limit": 10},
            )
            logger.info("persona_completed", persona=task.assigned_persona, task_id=task_id)

            result_content = result["messages"][-1].content if result.get("messages") else ""
            summary = _truncate_summary(result_content)

            output = TaskOutput(
                task_id=task_id,
                persona=task.assigned_persona,
                summary=summary,
                full_result=result_content,
                confidence=0.8,  # Success confidence
            )

            writer({"type": "task.completed_single", "data": {
                "thread_id": thread_id,
                "task_id": task_id,
                "persona": task.assigned_persona,
                "summary": summary[:200],
            }})

            return task_id, output

        except Exception as e:
            logger.error("task_execution_failed", task_id=task_id, error=str(e))

            output = TaskOutput(
                task_id=task_id,
                persona=task.assigned_persona,
                summary=TASK_EXECUTION_FAILED_SUMMARY.format(error=str(e)),
                full_result=str(e),
                confidence=0.0,  # Failure confidence
                metadata={"error": str(e)},
            )

            writer({"type": "task.failed_single", "data": {
                "thread_id": thread_id,
                "task_id": task_id,
                "error": str(e),
            }})

            return task_id, output

    # asyncio.gather — 并行执行，异常已在内部处理
    results = await asyncio.gather(
        *[run_single_safe(t) for t in ready_tasks]
    )

    # 收集结果
    new_outputs: dict[str, TaskOutput] = {}
    new_completed: list[str] = []

    for task_id, output in results:
        new_outputs[task_id] = output
        new_completed.append(task_id)

    # 通过 reducer 安全写入 state
    # task_outputs: merge_task_outputs reducer
    # completed_task_ids: operator.add reducer
    return {
        "task_outputs": new_outputs,
        "completed_task_ids": new_completed,
    }


# ============================================
# Node: Review (interrupt 隔离层)
# ============================================

async def review_node(state: BossState, config: RunnableConfig) -> dict:
    """
    检查执行结果 — interrupt 隔离层

    此时 execute_node 的结果已通过 reducer 安全写入 state。
    这是唯一允许在 execute 阶段触发 interrupt 的地方。

    检查项：
    - 失败的任务（confidence < 0.6）
    - 成本预算（可选）
    """
    writer = get_stream_writer()
    task_outputs = state.get("task_outputs", {})
    thread_id = state.get("thread_id", "")

    # 检查失败的任务
    failed = []
    for tid, out in task_outputs.items():
        confidence = _get(out, "confidence", 1.0)
        if isinstance(confidence, (int, float)) and confidence < 0.6:
            failed.append(tid)

    if failed:
        logger.warning("review_found_failed_tasks", failed=failed)

        # 安全地 interrupt — state 已持久化
        decision = interrupt({
            "type": "execution_review",
            "failed_tasks": failed,
            "failed_details": {
                tid: _get(task_outputs.get(tid, {}), "summary", "")
                for tid in failed
            },
            "message": f"{len(failed)} 个任务执行失败，是否继续？",
            "options": ["continue", "retry_failed", "cancel"],
        })

        action = decision.get("action") if isinstance(decision, dict) else decision

        if action == "cancel":
            return {"final_result": "任务已取消"}

        # "retry_failed" — MVP 简化：暂不实现，等同 continue
        # 完整实现需要从 completed_task_ids 和 task_outputs 中移除失败的
        # 由于 reducer 是 append-only 的，需要额外支持

    # TODO: 检查成本预算（可选）
    # budget_threshold = configurable.get("budget_threshold", float("inf"))
    # total_cost = sum(...)

    return {}  # 一切 OK，route_after_review 决定下一步


# ============================================
# Node: Aggregate
# ============================================

async def aggregate_node(state: BossState, config: RunnableConfig) -> dict:
    """
    Boss 汇总所有 Persona 结果生成最终报告

    单任务快速通道：跳过 LLM 汇总，直接返回结果
    多任务：LLM 汇总（流式）
    """
    writer = get_stream_writer()
    configurable = config.get("configurable", {})

    user_intent = state.get("user_intent", "")
    task_outputs: dict = state.get("task_outputs", {})
    thread_id = state.get("thread_id", "")

    # 如果已有 final_result（cancel 等场景），直接返回
    if state.get("final_result") is not None:
        writer({"type": "phase.change", "data": {
            "phase": "completed",
            "thread_id": thread_id,
        }})
        return {}

    # 获取依赖
    persona_factory = configurable.get("persona_factory")

    # 过滤掉 "final" key（如果存在）
    non_final = {k: v for k, v in task_outputs.items() if k != "final"}

    # 单任务快速通道
    if len(non_final) == 1:
        single_output = next(iter(non_final.values()))
        full_result = _get(single_output, "full_result", "")
        logger.info("aggregate_shortcut", thread_id=thread_id, reason="single_task")

        writer({"type": "phase.change", "data": {
            "phase": "aggregating",
            "thread_id": thread_id,
        }})

        # 流式发送结果
        chunk_size = 20
        for i in range(0, len(full_result), chunk_size):
            chunk = full_result[i:i + chunk_size]
            writer({"type": "llm.token", "data": {
                "thread_id": thread_id,
                "content": chunk,
                "node": "aggregate",
            }})
            await asyncio.sleep(0.01)  # yield control

        writer({"type": "phase.change", "data": {
            "phase": "completed",
            "thread_id": thread_id,
        }})

        return {
            "final_result": full_result,
            "task_outputs": {
                **task_outputs,
                "final": TaskOutput(
                    task_id="final",
                    persona="boss",
                    summary=FINAL_REPORT_SUMMARY,
                    full_result=full_result,
                    confidence=1.0,
                ),
            },
        }

    # 多任务：LLM 汇总（流式）
    task_summaries = "\n".join(
        f"[{tid}] ({_get(output, 'persona', 'unknown')}): {_get(output, 'summary', '')}"
        for tid, output in non_final.items()
    )

    # 标记失败任务
    failed_ids = [
        tid for tid, out in non_final.items()
        if _get(out, "confidence", 1.0) < 0.6
    ]
    if failed_ids:
        task_summaries += f"\n\n[WARNING] The following tasks failed during execution: {failed_ids}"

    prompt = BOSS_AGGREGATION_PROMPT.format(
        user_intent=user_intent,
        task_summaries=task_summaries,
    )

    writer({"type": "phase.change", "data": {
        "phase": "aggregating",
        "thread_id": thread_id,
    }})

    boss_model = persona_factory.model_router.get_model("writing")
    model_router = persona_factory.model_router
    messages = [
        SystemMessage(content=AGGREGATION_SYSTEM_MESSAGE),
        HumanMessage(content=prompt),
    ]

    full_result = ""
    async for chunk in model_router.astream_with_retry(boss_model, messages):
        token = chunk.content if hasattr(chunk, "content") else str(chunk)
        if token:
            full_result += token
            writer({"type": "llm.token", "data": {
                "thread_id": thread_id,
                "content": token,
                "node": "aggregate",
            }})

    writer({"type": "phase.change", "data": {
        "phase": "completed",
        "thread_id": thread_id,
    }})

    return {
        "final_result": full_result,
        "task_outputs": {
            **task_outputs,
            "final": TaskOutput(
                task_id="final",
                persona="boss",
                summary=FINAL_REPORT_SUMMARY,
                full_result=full_result,
                confidence=1.0,
            ),
        },
    }

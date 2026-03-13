"""
AgenticOS — REST API Routes
"""

from __future__ import annotations

import uuid
import asyncio

import structlog
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

logger = structlog.get_logger()
router = APIRouter()


# ============================================
# Request / Response Models
# ============================================

class TaskRequest(BaseModel):
    """用户任务请求"""
    intent: str
    config: dict = {}


class TaskResponse(BaseModel):
    """任务响应"""
    thread_id: str
    status: str
    result: str | None = None
    task_plan: dict | None = None


class HiTLResolveRequest(BaseModel):
    """HiTL 用户决定"""
    request_id: str
    decision: str
    feedback: str = ""


# ============================================
# Routes
# ============================================

@router.post("/tasks", response_model=TaskResponse)
async def create_task(req: TaskRequest, request: Request):
    """
    创建新任务
    用户意图 → Boss 分解 → Persona 执行 → 交付结果
    """
    thread_id = f"thread_{uuid.uuid4().hex[:12]}"
    boss_graph = request.app.state.boss_graph

    # 内存级任务追踪: 存储 asyncio.Task + 执行结果 (checkpointer 不可用时的 fallback)
    task_record = {"task": None, "result": None, "error": None, "status": "running"}
    request.app.state.active_tasks[thread_id] = task_record

    async def _run():
        try:
            config = {"configurable": {"thread_id": thread_id}}
            final_state = await boss_graph.ainvoke(
                {"user_intent": req.intent, "current_phase": "init", "thread_id": thread_id},
                config=config,
            )
            task_record["result"] = final_state
            task_record["status"] = "done"
            logger.info("task_completed", thread_id=thread_id)
        except Exception as e:
            task_record["error"] = str(e)
            task_record["status"] = "error"
            logger.error("task_execution_failed", thread_id=thread_id, error=str(e))

    # 异步执行: 不阻塞 HTTP 响应
    task = asyncio.create_task(_run())
    task_record["task"] = task

    # 广播 task.created 事件
    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        await ws_manager.broadcast({
            "type": "task.created",
            "thread_id": thread_id,
            "intent": req.intent,
        })

    return TaskResponse(
        thread_id=thread_id,
        status="running",
    )


@router.get("/tasks/{thread_id}")
async def get_task_status(thread_id: str, request: Request):
    """获取任务执行状态 — 优先 Checkpoint，fallback 内存追踪"""
    boss_graph = request.app.state.boss_graph

    # 优先尝试 LangGraph Checkpoint
    config = {"configurable": {"thread_id": thread_id}}
    try:
        state = await boss_graph.aget_state(config)
        if state is not None and state.values:
            return _format_state_response(thread_id, state.values)
    except Exception as e:
        logger.debug("checkpoint_read_failed", thread_id=thread_id, error=str(e))

    # Fallback: 内存级任务追踪
    task_record = request.app.state.active_tasks.get(thread_id)
    if task_record is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {thread_id}")

    if task_record["error"]:
        return {
            "thread_id": thread_id,
            "status": "error",
            "task_plan": None,
            "result": None,
            "error": task_record["error"],
            "hitl_pending": [],
        }

    if task_record["result"]:
        return _format_state_response(thread_id, task_record["result"])

    # 任务仍在执行中
    return {
        "thread_id": thread_id,
        "status": "running",
        "task_plan": None,
        "result": None,
        "hitl_pending": [],
    }


def _format_state_response(thread_id: str, values: dict) -> dict:
    """从状态 dict 构建统一的 API 响应"""
    phase = values.get("current_phase", "unknown")
    task_plan = values.get("task_plan")
    task_outputs = values.get("task_outputs", {})
    final_output = task_outputs.get("final")

    # 兼容 dict 和 Pydantic 对象
    plan_dict = None
    if task_plan:
        plan_dict = task_plan.model_dump() if hasattr(task_plan, "model_dump") else task_plan

    result = None
    if final_output:
        result = final_output.get("full_result") if isinstance(final_output, dict) else final_output.full_result

    hitl_pending = values.get("hitl_pending", [])
    hitl_list = [
        h.model_dump() if hasattr(h, "model_dump") else h
        for h in hitl_pending
    ]

    return {
        "thread_id": thread_id,
        "status": phase,
        "task_plan": plan_dict,
        "result": result,
        "hitl_pending": hitl_list,
    }


@router.post("/tasks/{thread_id}/hitl")
async def resolve_hitl(
    thread_id: str,
    req: HiTLResolveRequest,
    request: Request,
):
    """用户回应 HiTL 请求 — 记录决定 + 恢复 Graph 执行"""
    hitl_gateway = request.app.state.hitl_gateway
    boss_graph = request.app.state.boss_graph

    # 记录用户决定
    hitl_gateway.record_response(
        request_id=req.request_id,
        decision=req.decision,
        feedback=req.feedback,
    )

    # 恢复 Graph 执行
    config = {"configurable": {"thread_id": thread_id}}
    try:
        from core.state import HiTLResponse

        response = HiTLResponse(
            request_id=req.request_id,
            decision=req.decision,
            feedback=req.feedback,
        )
        await boss_graph.aupdate_state(
            config,
            {
                "hitl_resolved": [response],
                "hitl_pending": [],
                "current_phase": "executing",
            },
        )

        task_record = request.app.state.active_tasks.get(thread_id, {})

        async def _resume():
            try:
                final_state = await boss_graph.ainvoke(None, config=config)
                if isinstance(task_record, dict):
                    task_record["result"] = final_state
                    task_record["status"] = "done"
            except Exception as e:
                logger.error("hitl_resume_failed", thread_id=thread_id, error=str(e))
                if isinstance(task_record, dict):
                    task_record["error"] = str(e)
                    task_record["status"] = "error"

        task = asyncio.create_task(_resume())
        if isinstance(task_record, dict):
            task_record["task"] = task

        return {"status": "resumed", "request_id": req.request_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/personas")
async def list_personas(request: Request):
    """列出所有可用的 Persona"""
    factory = request.app.state.persona_factory
    return factory.list_personas()


@router.get("/tools")
async def list_tools(request: Request):
    """列出所有已注册工具"""
    registry = request.app.state.tool_registry
    return [
        {
            "name": t.name,
            "description": t.description,
            "source": t.source,
            "permission_level": t.permission_level,
        }
        for t in registry.list_tools()
    ]


@router.get("/scheduler/jobs")
async def list_scheduler_jobs(request: Request):
    """列出所有定时任务"""
    scheduler = request.app.state.scheduler
    jobs = scheduler.get_jobs()
    return [
        {
            "id": job.id,
            "name": job.name,
            "next_run_time": str(job.next_run_time),
        }
        for job in jobs
    ]

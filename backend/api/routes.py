"""
Usami — REST API Routes
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.auth import get_current_user
from core.event_store import delete_thread, get_thread_events, list_user_threads, persist_event
from core.state import UserProfile

logger = structlog.get_logger()
router = APIRouter()


# ============================================
# Request / Response Models
# ============================================

class TaskRequest(BaseModel):
    """用户任务请求"""
    intent: str
    config: dict = {}
    thread_id: str | None = None  # follow-up: reuse existing thread


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
# Helpers
# ============================================

async def _get_thread_last_result(thread_id: str) -> str | None:
    """Load the last task.completed result from event store (for follow-ups)."""
    events = await get_thread_events(thread_id)
    for evt in reversed(events):
        if evt.event_type == "task.completed":
            return evt.payload.get("result")
    return None


# ============================================
# Routes
# ============================================

@router.post("/tasks", response_model=TaskResponse)
async def create_task(req: TaskRequest, request: Request, _user: UserProfile = Depends(get_current_user)):
    """
    创建新任务
    用户意图 → Boss 分解 → Persona 执行 → 交付结果
    """
    # Follow-up: reuse thread_id, load previous result for context
    if req.thread_id:
        thread_id = req.thread_id
        previous_result = await _get_thread_last_result(thread_id)
    else:
        thread_id = f"thread_{uuid.uuid4().hex[:12]}"
        previous_result = None

    boss_graph = request.app.state.boss_graph

    # 内存级任务追踪: 存储 asyncio.Task + user_id (用于 SSE 路由)
    task_record = {"task": None, "user_id": _user.id}
    request.app.state.active_tasks[thread_id] = task_record

    async def _run():
        try:
            config = {"configurable": {"thread_id": thread_id}}
            initial_state = {
                "user_intent": req.intent,
                "current_phase": "init",
                "thread_id": thread_id,
            }
            if previous_result:
                initial_state["previous_result"] = previous_result
            await asyncio.wait_for(
                boss_graph.ainvoke(initial_state, config=config),
                timeout=600,  # 10 minutes
            )
            logger.info("task_completed", thread_id=thread_id)
        except asyncio.TimeoutError:
            logger.error("task_timeout", thread_id=thread_id)
            sse_manager = getattr(request.app.state, "sse_manager", None)
            if sse_manager:
                persisted = await persist_event(
                    thread_id, _user.id, "task.failed",
                    {"thread_id": thread_id, "task_id": "timeout", "error": "任务执行超时（10分钟）"},
                )
                await sse_manager.send_to_user(_user.id, persisted)
        except Exception as e:
            logger.error("task_execution_failed", thread_id=thread_id, error=str(e))

    # 异步执行: 不阻塞 HTTP 响应
    task = asyncio.create_task(_run())
    task_record["task"] = task

    # Persist + broadcast task.created event
    sse_manager = getattr(request.app.state, "sse_manager", None)
    if sse_manager:
        persisted = await persist_event(
            thread_id, _user.id, "task.created",
            {"thread_id": thread_id, "intent": req.intent},
        )
        await sse_manager.send_to_user(_user.id, persisted)

    return TaskResponse(
        thread_id=thread_id,
        status="running",
    )


@router.get("/tasks/{thread_id}")
async def get_task_status(thread_id: str, request: Request, _user: UserProfile = Depends(get_current_user)):
    """获取任务执行状态 — 从事件表派生"""
    events = await get_thread_events(thread_id)
    if not events:
        # Fallback: try LangGraph Checkpoint
        boss_graph = request.app.state.boss_graph
        config = {"configurable": {"thread_id": thread_id}}
        try:
            state = await boss_graph.aget_state(config)
            if state is not None and state.values:
                return _format_state_response(thread_id, state.values)
        except Exception as e:
            logger.debug("checkpoint_read_failed", thread_id=thread_id, error=str(e))

        raise HTTPException(status_code=404, detail=f"任务不存在: {thread_id}")

    # Derive state from events
    phase = "created"
    result = None
    task_plan = None
    error = None
    hitl_pending = []

    event_to_phase = {
        "task.created": "created",
        "task.planning": "planning",
        "task.plan_ready": "planned",
        "task.executing": "executing",
        "task.progress": "executing",
        "task.aggregating": "aggregating",
        "task.completed": "completed",
        "task.failed": "failed",
        "hitl.request": "hitl_waiting",
    }

    for evt in events:
        phase = event_to_phase.get(evt.event_type, phase)
        if evt.event_type == "task.completed":
            result = evt.payload.get("result")
        elif evt.event_type == "task.failed":
            error = evt.payload.get("error")
        elif evt.event_type == "task.plan_ready":
            task_plan = evt.payload.get("plan")
        elif evt.event_type == "hitl.request":
            hitl_pending.append(evt.payload.get("request", {}))

    return {
        "thread_id": thread_id,
        "status": phase,
        "task_plan": task_plan,
        "result": result,
        "error": error,
        "hitl_pending": hitl_pending,
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
    _user: UserProfile = Depends(get_current_user),
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

        # Notify via SSE that execution is resuming
        sse_manager = getattr(request.app.state, "sse_manager", None)
        if sse_manager:
            persisted = await persist_event(
                thread_id, _user.id, "task.executing",
                {"thread_id": thread_id, "task_id": "resume", "persona": "system"},
            )
            await sse_manager.send_to_user(_user.id, persisted)

        task_record = request.app.state.active_tasks.get(thread_id, {})

        async def _resume():
            try:
                await boss_graph.ainvoke(None, config=config)
            except Exception as e:
                logger.error("hitl_resume_failed", thread_id=thread_id, error=str(e))

        task = asyncio.create_task(_resume())
        if isinstance(task_record, dict):
            task_record["task"] = task

        return {"status": "resumed", "request_id": req.request_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/tasks/{thread_id}/cancel")
async def cancel_task(
    thread_id: str,
    request: Request,
    _user: UserProfile = Depends(get_current_user),
):
    """Cancel a running task."""
    task_record = request.app.state.active_tasks.get(thread_id)
    if not task_record or not isinstance(task_record, dict):
        raise HTTPException(status_code=404, detail="任务不存在")

    task = task_record.get("task")
    if task and not task.done():
        task.cancel()
        logger.info("task_cancelled", thread_id=thread_id)

        # Persist cancellation event
        sse_manager = getattr(request.app.state, "sse_manager", None)
        if sse_manager:
            persisted = await persist_event(
                thread_id, _user.id, "task.failed",
                {"thread_id": thread_id, "task_id": "cancel", "error": "任务已被用户取消"},
            )
            await sse_manager.send_to_user(_user.id, persisted)

        return {"status": "cancelled"}

    return {"status": "already_done"}


# ============================================
# Thread History Endpoints
# ============================================

@router.get("/threads")
async def list_threads(request: Request, user: UserProfile = Depends(get_current_user)):
    """List user's threads (from events table)."""
    threads = await list_user_threads(user.id)
    return threads


@router.get("/threads/{thread_id}/events")
async def get_thread_events_api(
    thread_id: str,
    request: Request,
    user: UserProfile = Depends(get_current_user),
    after_seq: int = 0,
):
    """Replay all events for a thread (for history loading)."""
    events = await get_thread_events(thread_id, after_seq=after_seq)
    return [e.model_dump() for e in events]


@router.delete("/threads/{thread_id}")
async def delete_thread_api(
    thread_id: str,
    request: Request,
    _user: UserProfile = Depends(get_current_user),
):
    """删除对话及其所有事件"""
    # Cancel running task if any
    task_record = request.app.state.active_tasks.get(thread_id)
    if task_record and isinstance(task_record, dict):
        task = task_record.get("task")
        if task and not task.done():
            task.cancel()
        request.app.state.active_tasks.pop(thread_id, None)

    deleted = await delete_thread(thread_id, _user.id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="对话不存在")
    logger.info("thread_deleted", thread_id=thread_id, user_id=_user.id)
    return {"status": "deleted"}


# ============================================
# Admin / Info Endpoints
# ============================================

@router.get("/personas")
async def list_personas(request: Request, _user: UserProfile = Depends(get_current_user)):
    """列出所有可用的 Persona"""
    factory = request.app.state.persona_factory
    return factory.list_personas()


@router.get("/tools")
async def list_tools(request: Request, _user: UserProfile = Depends(get_current_user)):
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
async def list_scheduler_jobs(request: Request, _user: UserProfile = Depends(get_current_user)):
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

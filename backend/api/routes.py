"""
Usami — REST API Routes (v2 Refactor)

v2 设计原则:
- POST /tasks: 只写 DB + pg_notify，不在进程内存执行
- POST /tasks/{id}/resume: CAS interrupted→resuming + INSERT resume_requests
- 并发检查基于数据库，不是内存
- 删除 asyncio.create_task, aupdate_state, active_tasks
"""

from __future__ import annotations

import json
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from core.auth import get_current_user
from core.event_store import delete_thread, get_thread_events, list_user_threads, verify_thread_ownership
from core.memory import get_session
from core.state import EVENT_PHASE_MAP, UserProfile
from core.task_queue import notify_new_task, notify_resume_task, persist_and_notify

logger = structlog.get_logger()
router = APIRouter()


# ============================================
# Request / Response Models
# ============================================

class TaskRequest(BaseModel):
    """用户任务请求"""
    intent: str = Field(min_length=1, max_length=5000)
    config: dict = {}
    thread_id: str | None = None  # follow-up: reuse existing thread


class TaskResponse(BaseModel):
    """任务响应"""
    thread_id: str
    status: str
    result: str | None = None
    task_plan: dict | None = None


class ResumeRequest(BaseModel):
    """HiTL 恢复请求"""
    action: str
    data: dict = {}


class HiTLResolveRequest(BaseModel):
    """HiTL 用户决定 (legacy, for backward compat)"""
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
# Routes (v2 — Database-driven)
# ============================================

@router.post("/tasks", response_model=TaskResponse)
async def create_task(request: Request, req: TaskRequest, user: UserProfile = Depends(get_current_user)):
    """
    创建新任务 (v2)

    1. 并发检查 (数据库，不是内存)
    2. INSERT INTO tasks
    3. pg_notify('new_task', ...) — 只传 ID
    4. 返回 {thread_id, status: "pending"}

    Worker 进程收到通知后执行图
    """
    logger.info("create_task_called", intent=req.intent, user_id=user.id)
    MAX_CONCURRENT_TASKS_PER_USER = 3

    try:
        async with get_session() as session:
            # 1. 并发检查（数据库）
            result = await session.execute(
                text("""
                    SELECT COUNT(*) FROM tasks
                    WHERE user_id = :user_id
                    AND status IN ('pending', 'running', 'interrupted', 'resuming')
                """),
                {"user_id": user.id},
            )
            active_count = result.scalar() or 0

            if active_count >= MAX_CONCURRENT_TASKS_PER_USER:
                raise HTTPException(status_code=429, detail="并发任务数已达上限")

            # Follow-up: reuse thread_id, load previous result for context
            if req.thread_id:
                thread_id = req.thread_id
                if not await verify_thread_ownership(thread_id, user.id):
                    raise HTTPException(status_code=404, detail="任务不存在")
                # Note: previous_result is loaded by Worker when executing
            else:
                thread_id = f"thread_{uuid.uuid4().hex[:12]}"

            # 2. 创建任务记录
            await session.execute(
                text("""
                    INSERT INTO tasks (thread_id, user_id, intent, status)
                    VALUES (:thread_id, :user_id, :intent, 'pending')
                    ON CONFLICT (thread_id) DO UPDATE SET
                        intent = :intent,
                        status = 'pending',
                        updated_at = NOW()
                """),
                {
                    "thread_id": thread_id,
                    "user_id": user.id,
                    "intent": req.intent,
                },
            )

            # 3. 持久化创建事件
            await persist_and_notify(
                session,
                thread_id,
                user.id,
                {
                    "type": "task.created",
                    "data": {"thread_id": thread_id, "intent": req.intent},
                },
            )

            # 4. pg_notify Worker（只传 ID）
            await notify_new_task(session, thread_id)

            await session.commit()

        logger.info("task_created", thread_id=thread_id, user_id=user.id)

        return TaskResponse(
            thread_id=thread_id,
            status="pending",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("create_task_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"创建任务失败: {e}")


@router.post("/tasks/{thread_id}/resume")
async def resume_task(
    thread_id: str,
    req: ResumeRequest,
    request: Request,
    user: UserProfile = Depends(get_current_user),
):
    """
    HiTL 恢复 (v2)

    1. 权限检查
    2. CAS: interrupted → resuming
    3. INSERT INTO resume_requests
    4. pg_notify('resume_task', ...) — 只传 ID
    """
    async with get_session() as session:
        # 1. 权限检查
        result = await session.execute(
            text("SELECT user_id, status FROM tasks WHERE thread_id = :thread_id"),
            {"thread_id": thread_id},
        )
        task = result.fetchone()

        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.user_id != user.id:
            raise HTTPException(status_code=403, detail="无权操作此任务")

        # 2. CAS: interrupted → resuming
        result = await session.execute(
            text("""
                UPDATE tasks SET status = 'resuming', updated_at = NOW()
                WHERE thread_id = :thread_id AND status = 'interrupted'
            """),
            {"thread_id": thread_id},
        )

        if result.rowcount == 0:
            raise HTTPException(
                status_code=409,
                detail=f"任务状态为 '{task.status}'，无法恢复（需要 'interrupted'）",
            )

        # 3. 持久化 resume 请求（Worker 崩溃后可恢复）
        await session.execute(
            text("""
                INSERT INTO resume_requests (thread_id, resume_value)
                VALUES (:thread_id, :resume_value)
            """),
            {
                "thread_id": thread_id,
                "resume_value": json.dumps({"action": req.action, "data": req.data}),
            },
        )

        # 4. pg_notify Worker（加速器，非可靠性保证）
        await notify_resume_task(session, thread_id)

        await session.commit()

    logger.info("task_resuming", thread_id=thread_id, user_id=user.id)

    return {"status": "resuming"}


@router.get("/tasks/{thread_id}")
async def get_task_status(thread_id: str, request: Request, user: UserProfile = Depends(get_current_user)):
    """获取任务执行状态 — 从 tasks 表 + events 表派生"""
    async with get_session() as session:
        # 先从 tasks 表获取状态
        result = await session.execute(
            text("SELECT user_id, status, intent FROM tasks WHERE thread_id = :thread_id"),
            {"thread_id": thread_id},
        )
        task = result.fetchone()

        if task:
            if task.user_id != user.id:
                raise HTTPException(status_code=403, detail="无权访问此任务")

            # 从 events 表获取详细信息
            events = await get_thread_events(thread_id)

            result_text = None
            task_plan = None
            error = None
            hitl_pending = []

            for evt in events:
                if evt.event_type == "task.completed":
                    result_text = evt.payload.get("result") or evt.payload.get("data", {}).get("result")
                elif evt.event_type == "task.failed":
                    error = evt.payload.get("error") or evt.payload.get("data", {}).get("error")
                elif evt.event_type in ("task.plan_ready", "phase.change"):
                    if "tasks" in evt.payload.get("data", {}):
                        task_plan = evt.payload["data"]
                elif evt.event_type == "interrupt":
                    hitl_pending.append(evt.payload.get("data", {}).get("value", {}))

            return {
                "thread_id": thread_id,
                "status": task.status,
                "intent": task.intent,
                "task_plan": task_plan,
                "result": result_text,
                "error": error,
                "hitl_pending": hitl_pending,
            }

    # Fallback: 检查 events 表（旧数据兼容）
    if not await verify_thread_ownership(thread_id, user.id):
        raise HTTPException(status_code=404, detail="任务不存在")

    events = await get_thread_events(thread_id)
    if not events:
        raise HTTPException(status_code=404, detail=f"任务不存在: {thread_id}")

    # Derive state from events (legacy)
    phase = "created"
    result_text = None
    task_plan = None
    error = None
    hitl_pending = []

    for evt in events:
        phase = EVENT_PHASE_MAP.get(evt.event_type, phase)
        if evt.event_type == "task.completed":
            result_text = evt.payload.get("result")
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
        "result": result_text,
        "error": error,
        "hitl_pending": hitl_pending,
    }


@router.post("/tasks/{thread_id}/hitl")
async def resolve_hitl(
    thread_id: str,
    req: HiTLResolveRequest,
    request: Request,
    user: UserProfile = Depends(get_current_user),
):
    """
    用户回应 HiTL 请求 (v2 — 转发到 /resume)

    为保持向后兼容，将旧的 HiTL 接口转发到新的 resume 接口
    """
    resume_req = ResumeRequest(
        action=req.decision,
        data={"request_id": req.request_id, "feedback": req.feedback},
    )

    return await resume_task(thread_id, resume_req, request, user)


@router.post("/tasks/{thread_id}/cancel")
async def cancel_task(
    thread_id: str,
    request: Request,
    user: UserProfile = Depends(get_current_user),
):
    """
    取消任务 (v2)

    只更新数据库状态，Worker 检测到状态变化会停止执行
    """
    async with get_session() as session:
        # 检查权限
        result = await session.execute(
            text("SELECT user_id, status FROM tasks WHERE thread_id = :thread_id"),
            {"thread_id": thread_id},
        )
        task = result.fetchone()

        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.user_id != user.id:
            raise HTTPException(status_code=403, detail="无权操作此任务")

        if task.status in ("completed", "failed"):
            return {"status": "already_done"}

        # 更新状态为 failed
        await session.execute(
            text("""
                UPDATE tasks SET status = 'failed', updated_at = NOW()
                WHERE thread_id = :thread_id
                AND status NOT IN ('completed', 'failed')
            """),
            {"thread_id": thread_id},
        )

        # 持久化取消事件
        await persist_and_notify(
            session,
            thread_id,
            user.id,
            {
                "type": "task.failed",
                "data": {"thread_id": thread_id, "error": "任务已被用户取消"},
            },
        )

        await session.commit()

    logger.info("task_cancelled", thread_id=thread_id, user_id=user.id)

    return {"status": "cancelled"}


# ============================================
# Thread History Endpoints
# ============================================

@router.get("/threads")
async def list_threads(request: Request, user: UserProfile = Depends(get_current_user)):
    """List user's threads (from tasks table + events table)."""
    async with get_session() as session:
        # 优先从 tasks 表获取
        result = await session.execute(
            text("""
                SELECT thread_id, intent, status, created_at, updated_at
                FROM tasks
                WHERE user_id = :user_id
                ORDER BY updated_at DESC
                LIMIT 100
            """),
            {"user_id": user.id},
        )
        tasks = result.fetchall()

        if tasks:
            return [
                {
                    "thread_id": t.thread_id,
                    "intent": t.intent,
                    "status": t.status,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                }
                for t in tasks
            ]

    # Fallback: 从 events 表获取（旧数据）
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
    if not await verify_thread_ownership(thread_id, user.id):
        raise HTTPException(status_code=404, detail="任务不存在")
    events = await get_thread_events(thread_id, after_seq=after_seq)
    return [e.model_dump() for e in events]


@router.delete("/threads/{thread_id}")
async def delete_thread_api(
    thread_id: str,
    request: Request,
    user: UserProfile = Depends(get_current_user),
):
    """删除对话及其所有事件"""
    async with get_session() as session:
        # 删除 tasks 表记录
        await session.execute(
            text("DELETE FROM tasks WHERE thread_id = :thread_id AND user_id = :user_id"),
            {"thread_id": thread_id, "user_id": user.id},
        )

        # 删除 resume_requests 表记录
        await session.execute(
            text("DELETE FROM resume_requests WHERE thread_id = :thread_id"),
            {"thread_id": thread_id},
        )

        await session.commit()

    # 删除 events 表记录
    deleted = await delete_thread(thread_id, user.id)

    if deleted == 0:
        raise HTTPException(status_code=404, detail="对话不存在")

    logger.info("thread_deleted", thread_id=thread_id, user_id=user.id)
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

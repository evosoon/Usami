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

    async def _run():
        try:
            config = {"configurable": {"thread_id": thread_id}}
            await boss_graph.ainvoke(
                {"user_intent": req.intent, "current_phase": "init"},
                config=config,
            )
            logger.info("task_completed", thread_id=thread_id)
        except Exception as e:
            logger.error("task_execution_failed", thread_id=thread_id, error=str(e))

    # 异步执行: 不阻塞 HTTP 响应
    task = asyncio.create_task(_run())
    request.app.state.active_tasks[thread_id] = task

    return TaskResponse(
        thread_id=thread_id,
        status="running",
    )


@router.get("/tasks/{thread_id}")
async def get_task_status(thread_id: str, request: Request):
    """获取任务执行状态 — 从 LangGraph Checkpoint 读取"""
    boss_graph = request.app.state.boss_graph

    config = {"configurable": {"thread_id": thread_id}}
    try:
        state = await boss_graph.aget_state(config)
        if state is None or not state.values:
            raise HTTPException(status_code=404, detail=f"Task not found: {thread_id}")

        values = state.values
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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

        # 继续执行
        async def _resume():
            try:
                await boss_graph.ainvoke(None, config=config)
            except Exception as e:
                logger.error("hitl_resume_failed", thread_id=thread_id, error=str(e))

        task = asyncio.create_task(_resume())
        request.app.state.active_tasks[thread_id] = task

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

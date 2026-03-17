"""
Usami — 全局 State Schema
Pre-mortem F3 修正: 结构化消息传递，非全局大 dict

设计原则:
- Agent 间传递「信封」(summary + reference)，不是「全文档」
- 每个 Task 的输出独立隔离
- Boss 通过 summary 做决策，需要详情时按 reference 获取
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

# ============================================
# Task & Plan Schema
# ============================================

class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"          # 等待依赖
    HITL_WAITING = "hitl_waiting"  # 等待人类介入


class Task(BaseModel):
    """单个子任务定义"""
    task_id: str
    title: str
    description: str
    assigned_persona: str         # Persona name from config
    task_type: str                # routing key: planning/research/writing/analysis
    dependencies: list[str] = []  # 依赖的 task_id 列表
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 0             # 0=normal, 1=high


class TaskPlan(BaseModel):
    """Boss 生成的任务执行计划 (DAG)"""
    plan_id: str
    user_intent: str
    tasks: list[Task]

    def get_ready_tasks(self, completed_ids: set[str]) -> list[Task]:
        """获取所有依赖已满足、可以执行的任务"""
        return [
            t for t in self.tasks
            if t.status == TaskStatus.PENDING
            and all(dep in completed_ids for dep in t.dependencies)
        ]


# ============================================
# Structured Message Passing (F3 修正核心)
# ============================================

class TaskOutput(BaseModel):
    """
    任务输出 — 信封模式
    summary: 传递给下游 Agent 的摘要（控制 token 消耗）
    full_result: 完整结果（按需获取）
    """
    task_id: str
    persona: str
    summary: str                  # ≤ 500 tokens，传递给下游
    full_result: str              # 完整输出，Boss 汇总时才读取
    artifacts: list[str] = []     # 产出物路径（文件、URL 等）
    confidence: float = 1.0       # 0-1，低于阈值触发 HiTL
    metadata: dict[str, Any] = {} # 路由日志等额外信息


# ============================================
# HiTL Event Schema
# ============================================

class HiTLType(StrEnum):
    CLARIFICATION = "clarification"   # 需要用户澄清意图
    APPROVAL = "approval"             # 需要用户批准操作
    CONFLICT = "conflict"             # 信息冲突，需要用户判断
    ERROR = "error"                   # 执行出错，需要用户介入
    PLAN_REVIEW = "plan_review"       # 计划预览（复杂任务）


class HiTLRequest(BaseModel):
    """HiTL 请求 — 推送给前端"""
    request_id: str
    hitl_type: HiTLType
    title: str
    description: str
    context: dict[str, Any] = {}   # 相关上下文
    options: list[str] = []         # 可选操作
    task_id: str | None = None   # 关联的任务
    persona: str | None = None   # 发起请求的 Persona


class HiTLResponse(BaseModel):
    """HiTL 响应 — 用户的决定"""
    request_id: str
    decision: str                  # 用户选择的操作
    feedback: str = ""             # 用户附加说明
    timestamp: str = ""


# ============================================
# Usami Global State (LangGraph State)
# ============================================

class AgentState(BaseModel):
    """
    LangGraph 全局状态对象

    设计原则 (F3 修正):
    - global_context: 所有 Agent 可见的全局信息
    - task_outputs: 按 task_id 隔离的输出（信封模式）
    - hitl_queue: HiTL 请求队列
    - execution_log: 执行日志（为 Progressive Trust 埋点）
    """
    # --- 全局上下文 ---
    user_intent: str = ""
    task_plan: TaskPlan | None = None
    current_phase: str = "init"   # init → planning → executing → aggregating → done

    # --- 任务输出 (信封模式) ---
    task_outputs: dict[str, TaskOutput] = {}
    completed_task_ids: set[str] = set()

    # --- HiTL ---
    hitl_pending: list[HiTLRequest] = []
    hitl_resolved: list[HiTLResponse] = []

    # --- 执行日志 (F8 修正: 为 Progressive Trust 埋数据) ---
    execution_log: list[dict[str, Any]] = []

    # --- 成本追踪 ---
    total_tokens: int = 0
    total_cost_usd: float = 0.0

    class Config:
        arbitrary_types_allowed = True


# ============================================
# Event Phase Mapping (single source of truth)
# ============================================

EVENT_PHASE_MAP: dict[str, str] = {
    "task.created": "created",
    "task.planning": "planning",
    "task.planning_chunk": "planning",
    "task.plan_ready": "planned",
    "task.executing": "executing",
    "task.progress": "executing",
    "task.aggregating": "aggregating",
    "task.result_chunk": "aggregating",
    "task.completed": "completed",
    "task.failed": "failed",
    "hitl.request": "hitl_waiting",
    "task.heartbeat": "executing",
}


# ============================================
# User & Auth Schema
# ============================================

class UserRole(StrEnum):
    ADMIN = "admin"
    USER = "user"


class UserProfile(BaseModel):
    """User profile returned by auth endpoints (no password)"""
    id: str
    email: str
    display_name: str
    role: UserRole
    is_active: bool


# ============================================
# Event Persistence Schema
# ============================================

class PersistedEvent(BaseModel):
    """Event as stored in DB and sent via SSE"""
    id: str
    thread_id: str
    user_id: str
    seq: int
    event_type: str
    payload: dict[str, Any] = {}
    created_at: str = ""

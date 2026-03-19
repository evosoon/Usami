"""
Usami — Cron Scheduler (v2)
定时任务调度 — 通过 pg_notify 触发 Worker 执行

v2 架构: Scheduler 只负责写入 tasks 表 + 发送 pg_notify，
        Worker 进程监听并执行实际的图调用。
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = structlog.get_logger()

SYSTEM_USER_ID = "system"


def init_scheduler(config: dict[str, Any], boss_graph=None) -> AsyncIOScheduler:
    """初始化定时调度器

    Note: boss_graph 参数保留用于健康检查，但不用于任务执行。
    """
    scheduler = AsyncIOScheduler()

    # 从配置加载预定义的定时任务
    scheduled_tasks = config.get("scheduled_tasks", [])
    for task_cfg in scheduled_tasks:
        _register_task(scheduler, task_cfg)

    logger.info("scheduler_initialized", task_count=len(scheduled_tasks))
    return scheduler


def _register_task(scheduler: AsyncIOScheduler, task_cfg: dict) -> None:
    """注册单个定时任务"""
    task_id = task_cfg.get("id", "unknown")
    cron_expr = task_cfg.get("cron", "0 9 * * *")  # 默认每天 9 点
    intent = task_cfg.get("intent", "")

    try:
        trigger = CronTrigger.from_crontab(cron_expr)
        scheduler.add_job(
            _execute_scheduled_task,
            trigger=trigger,
            id=task_id,
            name=task_cfg.get("name", task_id),
            kwargs={"intent": intent, "task_id": task_id},
            replace_existing=True,
        )
        logger.info("scheduled_task_registered", id=task_id, cron=cron_expr)
    except Exception as e:
        logger.error("scheduled_task_failed", id=task_id, error=str(e))


async def _execute_scheduled_task(intent: str, task_id: str) -> None:
    """执行定时触发的任务 — v2: 写入 DB + pg_notify"""
    logger.info("scheduled_task_triggered", task_id=task_id, intent=intent)

    thread_id = f"scheduled_{task_id}_{uuid.uuid4().hex[:8]}"

    try:
        from core.memory import get_session, Task
        from core.task_queue import notify_new_task

        # 写入 tasks 表
        async with get_session() as session:
            task = Task(
                thread_id=thread_id,
                user_id=SYSTEM_USER_ID,
                intent=intent,
                status="pending",
            )
            session.add(task)
            await session.commit()

        # 发送 pg_notify 通知 Worker
        await notify_new_task(thread_id)

        logger.info("scheduled_task_queued", task_id=task_id, thread_id=thread_id)
    except Exception as e:
        logger.error("scheduled_task_queue_failed", task_id=task_id, error=str(e))

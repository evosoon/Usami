"""
Usami — Cron Scheduler
定时任务调度 + 事件驱动触发

MVP: APScheduler Cron 调度
未来: + Redis Pub/Sub 事件驱动
"""

from __future__ import annotations

import uuid
import structlog
from typing import Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = structlog.get_logger()

# 模块级引用: Boss Graph (通过 init_scheduler 注入)
_boss_graph = None


def init_scheduler(config: dict[str, Any], boss_graph=None) -> AsyncIOScheduler:
    """初始化定时调度器"""
    global _boss_graph
    _boss_graph = boss_graph

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
    """执行定时触发的任务"""
    logger.info("scheduled_task_triggered", task_id=task_id, intent=intent)

    if _boss_graph is None:
        logger.error("scheduled_task_no_graph", task_id=task_id)
        return

    thread_id = f"scheduled_{task_id}_{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}
    try:
        await _boss_graph.ainvoke(
            {"user_intent": intent, "current_phase": "init", "thread_id": thread_id},
            config=config,
        )
        logger.info("scheduled_task_completed", task_id=task_id, thread_id=thread_id)
    except Exception as e:
        logger.error("scheduled_task_execution_failed", task_id=task_id, error=str(e))

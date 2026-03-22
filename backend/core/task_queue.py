"""
Usami — Task Queue (pg_notify helpers)
v2 Refactor: PostgreSQL LISTEN/NOTIFY for task coordination

设计原则:
- pg_notify payload < 100B (只传引用，不传完整数据)
- 完整事件写入 events 表，notify 只传 seq
- Worker 收到通知后从数据库读取完整数据
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


# ============================================
# Persistent Event Types (写入 events 表)
# ============================================

PERSISTENT_EVENTS = {
    "phase.change",
    "task.completed_single",
    "task.failed_single",
    "interrupt",
    "task.completed",
    "task.failed",
    "task.created",
    "node.completed",
}


# ============================================
# pg_notify Helpers
# ============================================

async def notify_new_task(session: AsyncSession, thread_id: str) -> None:
    """
    通知 Worker 有新任务

    payload: {"thread_id": "xxx"} (< 100B)
    """
    payload = json.dumps({"thread_id": thread_id})
    await session.execute(
        text("SELECT pg_notify('new_task', :payload)"),
        {"payload": payload},
    )
    logger.debug("pg_notify_new_task", thread_id=thread_id)


async def notify_resume_task(session: AsyncSession, thread_id: str) -> None:
    """
    通知 Worker 有任务需要恢复

    payload: {"thread_id": "xxx"} (< 100B)
    """
    payload = json.dumps({"thread_id": thread_id})
    await session.execute(
        text("SELECT pg_notify('resume_task', :payload)"),
        {"payload": payload},
    )
    logger.debug("pg_notify_resume_task", thread_id=thread_id)


async def notify_cancel_task(session: AsyncSession, thread_id: str) -> None:
    """
    通知 Worker 取消任务（事件驱动取消）

    Worker 收到后设置内存标记，stream 循环检查标记后停止执行
    payload: {"thread_id": "xxx"} (< 100B)
    """
    payload = json.dumps({"thread_id": thread_id})
    await session.execute(
        text("SELECT pg_notify('cancel_task', :payload)"),
        {"payload": payload},
    )
    logger.debug("pg_notify_cancel_task", thread_id=thread_id)


async def persist_and_notify(
    session: AsyncSession,
    thread_id: str,
    user_id: str,
    event: dict[str, Any],
) -> int:
    """
    持久化事件 + 轻量通知

    1. 写入 events 表（无大小限制）
    2. pg_notify 只传 seq + type（< 100B）

    Returns:
        seq: 事件序列号
    """
    import uuid

    event_type = event.get("type", "unknown")
    event_id = str(uuid.uuid4())

    # 1. 写入 events 表 (使用 CTE 避免参数类型推断问题)
    result = await session.execute(
        text("""
            WITH next_seq AS (
                SELECT COALESCE(MAX(seq), 0) + 1 AS val
                FROM events
                WHERE thread_id = :thread_id
            )
            INSERT INTO events (id, thread_id, user_id, seq, event_type, payload)
            SELECT :id, :thread_id, :user_id, next_seq.val, :event_type, :payload
            FROM next_seq
            RETURNING seq
        """),
        {
            "id": event_id,
            "thread_id": thread_id,
            "user_id": user_id,
            "event_type": event_type,
            "payload": json.dumps(event),
        },
    )
    row = result.fetchone()
    seq = row[0] if row else 0

    # 2. pg_notify 只传引用（远低于 8KB 限制）
    notification = json.dumps({
        "seq": seq,
        "type": event_type,
        "thread_id": thread_id,
    })
    await session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {
            "channel": f"events:{user_id}",
            "payload": notification,
        },
    )

    logger.debug(
        "event_persisted_and_notified",
        thread_id=thread_id,
        user_id=user_id,
        event_type=event_type,
        seq=seq,
    )

    return seq


async def persist_event_only(
    session: AsyncSession,
    thread_id: str,
    user_id: str,
    event: dict[str, Any],
) -> int:
    """
    仅持久化事件（不发送 pg_notify）

    用于批量写入场景，之后统一发送通知
    """
    import uuid

    event_type = event.get("type", "unknown")
    event_id = str(uuid.uuid4())

    result = await session.execute(
        text("""
            WITH next_seq AS (
                SELECT COALESCE(MAX(seq), 0) + 1 AS val
                FROM events
                WHERE thread_id = :thread_id
            )
            INSERT INTO events (id, thread_id, user_id, seq, event_type, payload)
            SELECT :id, :thread_id, :user_id, next_seq.val, :event_type, :payload
            FROM next_seq
            RETURNING seq
        """),
        {
            "id": event_id,
            "thread_id": thread_id,
            "user_id": user_id,
            "event_type": event_type,
            "payload": json.dumps(event),
        },
    )
    row = result.fetchone()
    return row[0] if row else 0


def is_persistent_event(event_type: str) -> bool:
    """判断事件是否需要持久化"""
    return event_type in PERSISTENT_EVENTS

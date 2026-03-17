"""
Usami — Event Store
Persist and retrieve SSE events from PostgreSQL.
Single source of truth for all task state and history.
"""
from __future__ import annotations

import uuid

import structlog
from sqlalchemy import func, select, text

from core.memory import Event, get_session
from core.state import PersistedEvent

logger = structlog.get_logger()


async def persist_event(
    thread_id: str,
    user_id: str,
    event_type: str,
    payload: dict,
) -> PersistedEvent:
    """Write an event to the DB with monotonically increasing per-thread seq."""
    session = get_session()
    try:
        # Assign next seq for this thread (safe: one writer per thread)
        result = await session.execute(
            select(func.coalesce(func.max(Event.seq), 0)).where(
                Event.thread_id == thread_id
            )
        )
        next_seq = result.scalar_one() + 1

        event_id = f"evt_{uuid.uuid4().hex[:16]}"
        event = Event(
            id=event_id,
            thread_id=thread_id,
            user_id=user_id,
            seq=next_seq,
            event_type=event_type,
            payload=payload,
        )
        session.add(event)
        await session.commit()

        logger.debug(
            "event_persisted",
            thread_id=thread_id,
            seq=next_seq,
            event_type=event_type,
        )

        return PersistedEvent(
            id=event_id,
            thread_id=thread_id,
            user_id=user_id,
            seq=next_seq,
            event_type=event_type,
            payload=payload,
            created_at=str(event.created_at or ""),
        )
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_thread_events(
    thread_id: str,
    after_seq: int = 0,
) -> list[PersistedEvent]:
    """Retrieve events for a thread, optionally after a given seq (for replay)."""
    session = get_session()
    try:
        stmt = (
            select(Event)
            .where(Event.thread_id == thread_id, Event.seq > after_seq)
            .order_by(Event.seq)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            PersistedEvent(
                id=row.id,
                thread_id=row.thread_id,
                user_id=row.user_id,
                seq=row.seq,
                event_type=row.event_type,
                payload=row.payload or {},
                created_at=str(row.created_at or ""),
            )
            for row in rows
        ]
    finally:
        await session.close()


async def list_user_threads(
    user_id: str,
    limit: int = 50,
) -> list[dict]:
    """List distinct threads for a user with summary info derived from events."""
    session = get_session()
    try:
        # Subquery: get first and last event per thread for this user
        stmt = text("""
            SELECT
                e.thread_id,
                MIN(e.created_at) AS created_at,
                MAX(e.created_at) AS updated_at,
                MAX(e.seq) AS last_seq,
                (SELECT ev.payload->>'intent'
                 FROM events ev
                 WHERE ev.thread_id = e.thread_id
                   AND ev.event_type = 'task.created'
                 ORDER BY ev.seq LIMIT 1
                ) AS intent,
                (SELECT ev.event_type
                 FROM events ev
                 WHERE ev.thread_id = e.thread_id
                 ORDER BY ev.seq DESC LIMIT 1
                ) AS latest_event_type,
                (SELECT ev.payload->>'result'
                 FROM events ev
                 WHERE ev.thread_id = e.thread_id
                   AND ev.event_type = 'task.completed'
                 ORDER BY ev.seq DESC LIMIT 1
                ) AS result
            FROM events e
            WHERE e.user_id = :user_id
            GROUP BY e.thread_id
            ORDER BY MAX(e.created_at) DESC
            LIMIT :limit
        """)
        result = await session.execute(stmt, {"user_id": user_id, "limit": limit})
        rows = result.fetchall()

        # Map latest_event_type to a phase
        event_to_phase = {
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

        return [
            {
                "thread_id": row.thread_id,
                "intent": row.intent or "",
                "latest_phase": event_to_phase.get(row.latest_event_type or "", "created"),
                "result": row.result,
                "created_at": str(row.created_at or ""),
                "updated_at": str(row.updated_at or ""),
            }
            for row in rows
        ]
    finally:
        await session.close()

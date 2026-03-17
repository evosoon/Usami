"""
Usami — Event Store
Persist and retrieve SSE events from PostgreSQL.
Single source of truth for all task state and history.
"""
from __future__ import annotations

import contextlib
import uuid

import structlog
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, insert, select, text

from core.memory import Event, TaskLog, get_session
from core.state import EVENT_PHASE_MAP, PersistedEvent

MAX_PAYLOAD_FIELD_SIZE = 100_000  # 100KB per field

logger = structlog.get_logger()


async def persist_event(
    thread_id: str,
    user_id: str,
    event_type: str,
    payload: dict,
    _max_retries: int = 2,
) -> PersistedEvent:
    """Write an event to the DB with monotonically increasing per-thread seq.

    Uses ORM insert with scalar subquery to prevent seq race conditions
    when parallel tasks persist events for the same thread.
    """
    # Truncate oversized payload fields to prevent DB bloat
    for key in ("result", "full_result"):
        if key in payload and isinstance(payload[key], str) and len(payload[key]) > MAX_PAYLOAD_FIELD_SIZE:
            payload = {**payload, key: payload[key][:MAX_PAYLOAD_FIELD_SIZE] + "\n\n... [truncated]"}

    event_id = f"evt_{uuid.uuid4().hex[:16]}"

    for attempt in range(_max_retries):
        async with get_session() as session:
            try:
                # Atomic seq via ORM: avoids raw SQL parameter binding issues with asyncpg
                next_seq_subq = (
                    select(func.coalesce(func.max(Event.seq), 0) + 1)
                    .where(Event.thread_id == thread_id)
                    .scalar_subquery()
                )
                stmt = (
                    insert(Event)
                    .values(
                        id=event_id,
                        thread_id=thread_id,
                        user_id=user_id,
                        seq=next_seq_subq,
                        event_type=event_type,
                        payload=payload,
                    )
                    .returning(Event.seq, Event.created_at)
                )
                result = await session.execute(stmt)
                row = result.one()
                next_seq = row.seq
                created_at = row.created_at
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
                    created_at=str(created_at or ""),
                )
            except Exception as e:
                await session.rollback()
                # Retry on unique constraint violation (seq collision)
                if attempt < _max_retries - 1 and "uq_events_thread_seq" in str(e):
                    event_id = f"evt_{uuid.uuid4().hex[:16]}"
                    logger.warning("event_seq_collision_retry", thread_id=thread_id, attempt=attempt)
                    continue
                raise


async def verify_thread_ownership(thread_id: str, user_id: str) -> bool:
    """Check if a user owns a thread (has at least one event in it)."""
    async with get_session() as session:
        result = await session.execute(
            select(func.count()).select_from(Event).where(
                Event.thread_id == thread_id, Event.user_id == user_id
            )
        )
        return result.scalar_one() > 0


async def get_thread_events(
    thread_id: str,
    after_seq: int = 0,
) -> list[PersistedEvent]:
    """Retrieve events for a thread, optionally after a given seq (for replay)."""
    async with get_session() as session:
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


async def list_user_threads(
    user_id: str,
    limit: int = 50,
) -> list[dict]:
    """List distinct threads for a user with summary info derived from events."""
    async with get_session() as session:
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

        return [
            {
                "thread_id": row.thread_id,
                "intent": row.intent or "",
                "latest_phase": EVENT_PHASE_MAP.get(row.latest_event_type or "", "created"),
                "result": row.result,
                "created_at": str(row.created_at or ""),
                "updated_at": str(row.updated_at or ""),
            }
            for row in rows
        ]


async def delete_thread(thread_id: str, user_id: str) -> int:
    """Delete all data for a thread. Returns deleted event count. Checks ownership via user_id."""
    async with get_session() as session:
        try:
            # Verify ownership: at least one event belongs to this user
            result = await session.execute(
                select(func.count()).select_from(Event).where(
                    Event.thread_id == thread_id, Event.user_id == user_id
                )
            )
            if result.scalar_one() == 0:
                return 0

            # Delete events
            result = await session.execute(
                sa_delete(Event).where(Event.thread_id == thread_id)
            )
            deleted_count = result.rowcount

            # Delete task_logs
            await session.execute(
                sa_delete(TaskLog).where(TaskLog.thread_id == thread_id)
            )

            # Delete LangGraph checkpoint tables (may not exist in all environments)
            for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                with contextlib.suppress(Exception):
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE thread_id = :tid"),
                        {"tid": thread_id},
                    )

            await session.commit()
            logger.info("thread_deleted", thread_id=thread_id, deleted_events=deleted_count)
            return deleted_count
        except Exception:
            await session.rollback()
            raise

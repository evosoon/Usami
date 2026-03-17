"""
Usami — SSE (Server-Sent Events) Endpoint
Replaces WebSocket for real-time server-to-client event streaming.
Per-user directed event routing with multi-tab support.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from core.auth import get_current_user
from core.event_store import get_thread_events
from core.state import PersistedEvent, UserProfile

logger = structlog.get_logger()

router = APIRouter()


# ============================================
# SSE Connection Manager
# ============================================

class SSEConnectionManager:
    """Per-user directed event routing, supporting multi-tab and multi-worker via Redis pub/sub."""

    def __init__(self, redis_client: Any | None = None) -> None:
        # user_id -> list of asyncio.Queue (one per tab/connection)
        self._connections: dict[str, list[asyncio.Queue]] = {}
        self._redis = redis_client

    def connect(self, user_id: str) -> asyncio.Queue:
        """Register a new SSE connection for a user. Returns the queue to read from."""
        queue: asyncio.Queue = asyncio.Queue()
        self._connections.setdefault(user_id, []).append(queue)
        logger.info("sse_connected", user_id=user_id, tabs=len(self._connections[user_id]))
        return queue

    def disconnect(self, user_id: str, queue: asyncio.Queue) -> None:
        """Remove an SSE connection."""
        conns = self._connections.get(user_id, [])
        try:
            conns.remove(queue)
        except ValueError:
            pass
        if not conns:
            self._connections.pop(user_id, None)
        logger.info("sse_disconnected", user_id=user_id, tabs=len(conns))

    async def send_to_user(self, user_id: str, event: PersistedEvent) -> None:
        """Send event to all tabs of a user on THIS worker."""
        for queue in self._connections.get(user_id, []):
            try:
                await queue.put(event)
            except Exception as e:
                logger.warning("sse_queue_put_failed", user_id=user_id, error=str(e))

    async def broadcast_event(self, user_id: str, event: PersistedEvent) -> None:
        """Publish event via Redis pub/sub for cross-worker distribution.

        Falls back to local-only delivery when Redis is unavailable.
        """
        if self._redis:
            try:
                await self._redis.publish(
                    f"usami:sse:{user_id}",
                    event.model_dump_json(),
                )
                return
            except Exception as e:
                logger.warning("sse_redis_publish_failed", user_id=user_id, error=str(e))
        # Single-worker fallback
        await self.send_to_user(user_id, event)

    async def start_subscription(self) -> None:
        """Subscribe to Redis for events targeted at users connected to this worker."""
        if not self._redis:
            return
        try:
            pubsub = self._redis.pubsub()
            await pubsub.psubscribe("usami:sse:*")
            logger.info("sse_redis_subscription_started")
            async for msg in pubsub.listen():
                if msg["type"] == "pmessage":
                    user_id = msg["channel"].decode().split(":")[-1]
                    event = PersistedEvent.model_validate_json(msg["data"])
                    await self.send_to_user(user_id, event)
        except asyncio.CancelledError:
            logger.info("sse_redis_subscription_stopped")
        except Exception as e:
            logger.error("sse_redis_subscription_error", error=str(e))

    @property
    def active_connections(self) -> int:
        return sum(len(qs) for qs in self._connections.values())


# ============================================
# SSE Format Helpers
# ============================================

def format_sse(event: PersistedEvent) -> str:
    """Format a persisted event as SSE wire format."""
    data = json.dumps(
        {"thread_id": event.thread_id, "seq": event.seq, **event.payload},
        ensure_ascii=False,
    )
    return (
        f"id: {event.id}\n"
        f"event: {event.event_type}\n"
        f"data: {data}\n\n"
    )


def format_keepalive() -> str:
    """SSE comment for keepalive (not dispatched as event by EventSource)."""
    return ": keepalive\n\n"


# ============================================
# SSE Endpoint
# ============================================

MAX_SSE_CONNECTIONS_PER_USER = 5


@router.get("/events/stream")
async def sse_stream(
    request: Request,
    user: UserProfile = Depends(get_current_user),
):
    """
    SSE event stream — one per browser tab.

    Auth: access_token cookie (automatic via browser).
    Replay: Pass last_event_id query param for missed event replay.
    Keepalive: Server sends comment every 15s on idle.
    """
    sse_manager: SSEConnectionManager = request.app.state.sse_manager

    # Enforce per-user connection limit
    current_count = len(sse_manager._connections.get(user.id, []))
    if current_count >= MAX_SSE_CONNECTIONS_PER_USER:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=429,
            content={"detail": "SSE 连接数已达上限"},
        )

    last_event_id = (
        request.headers.get("Last-Event-ID")
        or request.query_params.get("last_event_id")
    )

    async def event_generator():
        queue = sse_manager.connect(user.id)
        try:
            # Replay missed events if Last-Event-ID provided
            if last_event_id:
                await _replay_missed(user.id, last_event_id, queue)

            # Stream live events with keepalive
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield format_sse(event)
                except asyncio.TimeoutError:
                    yield format_keepalive()

                # Check if client disconnected
                if await request.is_disconnected():
                    break
        except asyncio.CancelledError:
            pass
        finally:
            sse_manager.disconnect(user.id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _replay_missed(
    user_id: str,
    last_event_id: str,
    queue: asyncio.Queue,
) -> None:
    """Replay missed events since last_event_id by querying the events table."""
    try:
        # Find the seq of the last received event
        from core.memory import Event, get_session
        from sqlalchemy import select

        async with get_session() as session:
            result = await session.execute(
                select(Event.thread_id, Event.seq).where(Event.id == last_event_id)
            )
            row = result.first()
            if not row:
                return

            # Get all events for this user's threads after the given seq
            # We replay ALL threads, not just the one from last_event_id
            events = await get_thread_events(row.thread_id, after_seq=row.seq)
            for event in events:
                if event.user_id == user_id:
                    await queue.put(event)
    except Exception as e:
        logger.warning("sse_replay_failed", user_id=user_id, error=str(e))

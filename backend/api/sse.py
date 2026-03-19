"""
Usami — SSE (Server-Sent Events) Endpoint (v2 Refactor)

v2 设计原则:
- 双通道: pg LISTEN (持久化事件) + Redis subscribe (瞬态事件)
- 时序保证: 先 LISTEN 后查询（确保不漏不重）
- seq 去重: 防止补发与实时流的重叠
- Last-Event-ID 支持: 浏览器自动重连时的事件恢复

时序协议:
    T0: LISTEN events:{user_id}          ← 先监听
    T1: SELECT events WHERE seq > last   ← 再查历史
    T2: yield events [last+1, ...]       ← 补发
    T3: Worker 产生 event N, pg_notify   ← 通知进入 queue
    T4: queue.get() → seq=N > last_sent  ← 实时推送（不漏）
    T5: seq 去重                          ← 不重复发送
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import asyncpg
import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from core.auth import get_current_user
from core.state import PersistedEvent, UserProfile

logger = structlog.get_logger()

router = APIRouter()


# ============================================
# SSE Format Helpers
# ============================================

def format_sse_persistent(seq: int, event_type: str, payload: str) -> str:
    """Format a persistent event as SSE wire format (with id for replay)."""
    return (
        f"id: {seq}\n"
        f"event: {event_type}\n"
        f"data: {payload}\n\n"
    )


def format_sse_transient(event_type: str, payload: str) -> str:
    """Format a transient event as SSE wire format (no id — not replayable)."""
    return (
        f"event: {event_type}\n"
        f"data: {payload}\n\n"
    )


def format_keepalive() -> str:
    """SSE comment for keepalive (not dispatched as event by EventSource)."""
    return ": keepalive\n\n"


# ============================================
# SSE Endpoint (v2 — Dual Channel)
# ============================================

MAX_SSE_CONNECTIONS_PER_USER = 5


@router.get("/events/stream")
async def sse_stream(
    request: Request,
    user: UserProfile = Depends(get_current_user),
    last_seq: int = Query(0, description="Last received sequence number"),
    thread_id: str | None = Query(None, description="Filter by thread ID"),
):
    """
    SSE event stream (v2) — 双通道 + 时序保证

    Auth: access_token cookie (automatic via browser).
    Replay:
        - last_seq query param: 前端主动传（刷新页面场景）
        - Last-Event-ID header: 浏览器自动重连时发送
    Keepalive: Server sends comment every 30s on idle.

    事件分类:
        - 持久化事件 (有 id=seq): phase.change, interrupt, task.completed 等
        - 瞬态事件 (无 id): llm.token, heartbeat
    """
    # 优先用 SSE 规范的 Last-Event-ID（自动重连场景）
    header_last_id = request.headers.get("Last-Event-ID")
    effective_last_seq = int(header_last_id) if header_last_id else last_seq

    # 获取数据库连接信息
    from core.config import load_config
    config = load_config()
    database_url = os.getenv("DATABASE_URL", config.database_url)
    redis_url = os.getenv("REDIS_URL", config.redis_url)
    dsn = database_url.replace("postgresql://", "postgres://")

    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)  # 背压
        listen_conn = None
        redis_client = None
        redis_task = None

        try:
            # ══ Phase 1: 先 LISTEN（确保不漏通知） ══
            listen_conn = await asyncpg.connect(dsn)
            channel = f"events:{user.id}"

            def on_pg_notify(conn, pid, ch, payload):
                try:
                    queue.put_nowait(("pg", payload))
                except asyncio.QueueFull:
                    logger.warning("sse_queue_full", user_id=user.id)

            await listen_conn.add_listener(channel, on_pg_notify)
            logger.debug("sse_listening", user_id=user.id, channel=channel)

            # Redis 订阅（瞬态事件）
            import redis.asyncio as aioredis
            redis_client = await aioredis.from_url(redis_url)
            redis_sub = redis_client.pubsub()
            await redis_sub.subscribe(f"stream:{user.id}")

            async def redis_reader():
                try:
                    async for message in redis_sub.listen():
                        if message["type"] == "message":
                            try:
                                queue.put_nowait(("redis", message["data"]))
                            except asyncio.QueueFull:
                                pass  # 瞬态事件丢了就丢了
                except asyncio.CancelledError:
                    pass

            redis_task = asyncio.create_task(redis_reader())

            # ══ Phase 2: 补发历史（LISTEN 已经在接收新通知） ══
            pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
            try:
                async with pool.acquire() as conn:
                    if thread_id:
                        missed = await conn.fetch(
                            """
                            SELECT seq, event_type, payload FROM events
                            WHERE user_id = $1 AND thread_id = $2 AND seq > $3
                            ORDER BY seq
                            """,
                            user.id, thread_id, effective_last_seq,
                        )
                    else:
                        missed = await conn.fetch(
                            """
                            SELECT seq, event_type, payload FROM events
                            WHERE user_id = $1 AND seq > $2
                            ORDER BY seq
                            """,
                            user.id, effective_last_seq,
                        )

                # ⚠️ seq 是 per-thread 的！使用 (thread_id, seq) 组合去重
                sent_events: set[tuple[str, int]] = set()
                for evt in missed:
                    # 从 payload 提取 thread_id
                    try:
                        payload_data = json.loads(evt["payload"]) if isinstance(evt["payload"], str) else evt["payload"]
                        evt_thread_id = payload_data.get("data", {}).get("thread_id") or payload_data.get("thread_id", "")
                    except Exception:
                        evt_thread_id = ""

                    sent_events.add((evt_thread_id, evt["seq"]))
                    yield format_sse_persistent(
                        evt["seq"],
                        evt["event_type"],
                        evt["payload"] if isinstance(evt["payload"], str) else json.dumps(evt["payload"]),
                    )

                # ══ Phase 3: 消费实时流 ══
                while not await request.is_disconnected():
                    try:
                        source, payload_str = await asyncio.wait_for(
                            queue.get(),
                            timeout=30,
                        )

                        if source == "pg":
                            # 持久化事件通知
                            meta = json.loads(payload_str)
                            evt_thread_id = meta.get("thread_id", "")
                            evt_seq = meta["seq"]

                            # 去重：使用 (thread_id, seq) 组合
                            if (evt_thread_id, evt_seq) in sent_events:
                                continue

                            # 可选 thread_id 过滤
                            if thread_id and evt_thread_id != thread_id:
                                continue

                            # 从 DB 读完整事件
                            async with pool.acquire() as conn:
                                event = await conn.fetchrow(
                                    "SELECT event_type, payload FROM events WHERE thread_id = $1 AND seq = $2",
                                    evt_thread_id, evt_seq,
                                )

                            if event:
                                payload_str = event["payload"] if isinstance(event["payload"], str) else json.dumps(event["payload"])
                                yield format_sse_persistent(
                                    evt_seq,
                                    event["event_type"],
                                    payload_str,
                                )
                                sent_events.add((evt_thread_id, evt_seq))

                        elif source == "redis":
                            # 瞬态事件 — 无 id，不持久化
                            if isinstance(payload_str, bytes):
                                payload_str = payload_str.decode()
                            event_data = json.loads(payload_str)

                            # 可选 thread_id 过滤
                            if thread_id and event_data.get("thread_id") != thread_id:
                                continue

                            yield format_sse_transient(
                                event_data.get("type", "custom"),
                                payload_str,
                            )

                    except asyncio.TimeoutError:
                        yield format_keepalive()

            finally:
                await pool.close()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("sse_stream_error", user_id=user.id, error=str(e))
        finally:
            if redis_task:
                redis_task.cancel()
                try:
                    await redis_task
                except asyncio.CancelledError:
                    pass
            if redis_client:
                await redis_client.close()
            if listen_conn:
                try:
                    await listen_conn.remove_listener(channel, on_pg_notify)
                except Exception:
                    pass
                await listen_conn.close()
            logger.debug("sse_disconnected", user_id=user.id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================
# SSE Connection Manager (v2 — minimal stub for health check)
# ============================================

class SSEConnectionManager:
    """
    v2 架构: SSE 通过 pg_notify 端点直接管理，此类仅用于 health check 指标。
    实际的 SSE 连接计数应从 /events/stream 端点的活跃连接数获取。
    """

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client
        # v2: 连接数由 pg_notify SSE 端点跟踪，此处仅为占位
        self._connection_count = 0

    @property
    def active_connections(self) -> int:
        """返回当前活跃 SSE 连接数（v2 中为占位值）"""
        return self._connection_count

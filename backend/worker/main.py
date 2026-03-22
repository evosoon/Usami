"""
Usami — Worker Process
v2 Refactor: 独立进程消费 pg_notify，执行 LangGraph 图

设计原则:
- 专用 LISTEN 连接（不占 pool）
- CAS 保证并发安全
- 启动时恢复孤儿任务
- 双通道事件分发（PostgreSQL + Redis）
- 事件驱动取消（pg_notify 推送，非轮询）

运行方式:
    python -m worker.main

架构:
    pg_notify('new_task', '{"thread_id":"..."}')     → handle_new_task()
    pg_notify('resume_task', '{"thread_id":"..."}') → handle_resume_task()
    pg_notify('cancel_task', '{"thread_id":"..."}') → 设置取消标记
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from typing import Any

import asyncpg
import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.boss import build_boss_graph
from core.config import load_config
from core.memory import init_database
from core.persona_factory import PersonaFactory
from core.task_queue import is_persistent_event

logger = structlog.get_logger()


# ============================================
# Cancellation Registry (事件驱动取消)
# ============================================

class CancellationRegistry:
    """
    内存中的取消标记注册表

    工作流程：
    1. API 删除/取消任务时 → pg_notify('cancel_task', thread_id)
    2. Worker 收到通知 → registry.cancel(thread_id)
    3. stream 循环检查 → registry.is_cancelled(thread_id)（纯内存，零 DB 开销）
    4. 任务结束 → registry.cleanup(thread_id)
    """

    def __init__(self):
        self._cancelled: set[str] = set()
        self._lock = asyncio.Lock()

    async def cancel(self, thread_id: str) -> None:
        async with self._lock:
            self._cancelled.add(thread_id)
        logger.info("task_cancellation_registered", thread_id=thread_id)

    def is_cancelled(self, thread_id: str) -> bool:
        """同步检查，用于 stream 循环中的快速判断"""
        return thread_id in self._cancelled

    async def cleanup(self, thread_id: str) -> None:
        async with self._lock:
            self._cancelled.discard(thread_id)


# Global registry instance
cancellation_registry = CancellationRegistry()


# ============================================
# Stream Event Dispatch (双通道)
# ============================================

async def dispatch_stream_chunk(
    pool: asyncpg.Pool,
    redis,
    thread_id: str,
    user_id: str,
    chunk: tuple | dict,
) -> None:
    """
    将 LangGraph stream chunk 分发到双通道

    LangGraph astream with stream_mode=["messages", "updates", "custom"] returns:
        - ('messages', (msg, metadata))
        - ('updates', {node_name: output})
        - ('custom', {type: ..., data: ...})

    持久化事件 → PostgreSQL + pg_notify
    瞬态事件 → Redis pub/sub
    """
    # LangGraph astream returns tuples: (stream_mode, data)
    if isinstance(chunk, tuple) and len(chunk) == 2:
        chunk_type, chunk_data = chunk
    else:
        # Fallback for dict format
        chunk_type = chunk.get("type", "") if isinstance(chunk, dict) else ""
        chunk_data = chunk.get("data", {}) if isinstance(chunk, dict) else {}

    if chunk_type == "messages":
        # LLM token → 瞬态通道（Redis pub/sub）
        if isinstance(chunk_data, tuple) and len(chunk_data) >= 2:
            msg, metadata = chunk_data[0], chunk_data[1]
            content = getattr(msg, "content", "") if hasattr(msg, "content") else ""
            if content:
                await redis.publish(
                    f"stream:{user_id}",
                    json.dumps({
                        "type": "llm.token",
                        "thread_id": thread_id,
                        "content": content,
                        "node": metadata.get("langgraph_node", "") if isinstance(metadata, dict) else "",
                    }),
                )

    elif chunk_type == "custom":
        event_data = chunk_data if isinstance(chunk_data, dict) else {}
        event_type = event_data.get("type", "custom")

        if is_persistent_event(event_type):
            # 持久化事件 → PostgreSQL + pg_notify
            await persist_and_notify(pool, thread_id, user_id, event_data)
        else:
            # 未知类型 → 默认瞬态
            await redis.publish(
                f"stream:{user_id}",
                json.dumps({**event_data, "thread_id": thread_id}),
            )

    elif chunk_type == "updates":
        # 节点完成 → 持久化（用于断线重连）
        data = chunk_data if isinstance(chunk_data, dict) else {}
        for node_name in data:
            await persist_and_notify(pool, thread_id, user_id, {
                "type": "node.completed",
                "data": {"node": node_name, "thread_id": thread_id},
            })


async def persist_and_notify(
    pool: asyncpg.Pool,
    thread_id: str,
    user_id: str,
    event: dict[str, Any],
) -> int:
    """持久化事件 + 轻量通知（< 100 bytes）"""
    import uuid

    event_type = event.get("type", "unknown")
    event_id = str(uuid.uuid4())

    async with pool.acquire() as conn:
        # 1. 写入 events 表 (使用 CTE 避免参数类型推断问题)
        row = await conn.fetchrow(
            """
            WITH next_seq AS (
                SELECT COALESCE(MAX(seq), 0) + 1 AS val
                FROM events
                WHERE thread_id = $1
            )
            INSERT INTO events (id, thread_id, user_id, seq, event_type, payload)
            SELECT $2, $1, $3, next_seq.val, $4, $5
            FROM next_seq
            RETURNING seq
            """,
            thread_id, event_id, user_id, event_type, json.dumps(event),
        )
        seq = row["seq"] if row else 0

        # 2. pg_notify 只传引用（远低于 8KB 限制）
        notification = json.dumps({
            "seq": seq,
            "type": event_type,
            "thread_id": thread_id,
        })
        await conn.execute(
            "SELECT pg_notify($1, $2)",
            f"events:{user_id}",
            notification,
        )

    logger.debug(
        "event_persisted",
        thread_id=thread_id,
        event_type=event_type,
        seq=seq,
    )
    return seq


# ============================================
# Task Handlers
# ============================================

async def finalize_task(
    pool: asyncpg.Pool,
    redis,
    graph,
    thread_id: str,
    user_id: str,
    config: dict,
) -> None:
    """检查图执行是否 interrupt 或 completed"""
    state_snapshot = await graph.aget_state(config)

    has_interrupt = (
        state_snapshot.tasks
        and any(task.interrupts for task in state_snapshot.tasks)
    )

    async with pool.acquire() as conn:
        if has_interrupt:
            # 提取 interrupt payload 通知前端
            for task in state_snapshot.tasks:
                for intr in task.interrupts:
                    await persist_and_notify(pool, thread_id, user_id, {
                        "type": "interrupt",
                        "data": {"value": intr.value, "thread_id": thread_id},
                    })

            await conn.execute(
                "UPDATE tasks SET status='interrupted', updated_at=NOW() "
                "WHERE thread_id=$1",
                thread_id,
            )
            logger.info("task_interrupted", thread_id=thread_id)

        elif not state_snapshot.next:
            # 图执行完毕 — 提取 final_result
            final_result = state_snapshot.values.get("final_result", "")
            await persist_and_notify(pool, thread_id, user_id, {
                "type": "task.completed",
                "data": {"thread_id": thread_id, "result": final_result},
            })
            await conn.execute(
                "UPDATE tasks SET status='completed', updated_at=NOW() "
                "WHERE thread_id=$1",
                thread_id,
            )
            logger.info("task_completed", thread_id=thread_id)


def is_task_cancelled(thread_id: str) -> bool:
    """
    检查任务是否已被取消（纯内存检查，零 DB 开销）

    由 CancellationRegistry 维护，通过 pg_notify 实时更新
    """
    return cancellation_registry.is_cancelled(thread_id)


async def handle_new_task(
    pool: asyncpg.Pool,
    graph,
    redis,
    persona_factory: PersonaFactory,
    data: dict,
) -> None:
    """处理新任务"""
    thread_id = data["thread_id"]

    # CAS: pending → running（多 Worker 竞争时只有一个成功）
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE tasks SET status='running', updated_at=NOW() "
            "WHERE thread_id=$1 AND status='pending'",
            thread_id,
        )
        if result == "UPDATE 0":
            logger.debug("task_already_claimed", thread_id=thread_id)
            return  # 已被其他 Worker 抢到

        task = await conn.fetchrow(
            "SELECT user_id, intent FROM tasks WHERE thread_id=$1",
            thread_id,
        )

        # 追问上下文：获取上一次完成的结果
        previous_result = None
        prev_row = await conn.fetchrow(
            """
            SELECT payload->'data'->>'result' as result
            FROM events
            WHERE thread_id=$1 AND event_type='task.completed'
            ORDER BY seq DESC LIMIT 1
            """,
            thread_id,
        )
        if prev_row and prev_row["result"]:
            previous_result = prev_row["result"]
            logger.info("follow_up_context_loaded", thread_id=thread_id, prev_len=len(previous_result))

    if not task:
        logger.error("task_not_found", thread_id=thread_id)
        return

    user_id = task["user_id"]
    config = {
        "configurable": {
            "thread_id": thread_id,
            "persona_factory": persona_factory,
            "validator": None,  # Will be created in graph builder
            "available_personas": persona_factory.list_personas(),
        }
    }
    # ⚠️ 重要：每次新任务必须重置 state，否则 completed_task_ids 会累积导致新任务被跳过
    initial_state = {
        "user_intent": task["intent"],
        "thread_id": thread_id,
        # 重置执行状态（清空上一轮的结果）
        "task_plan": None,
        "task_outputs": {},
        "completed_task_ids": [],
        "final_result": None,
        # 追问上下文：保留上一轮的结果
        "previous_result": previous_result,
    }

    logger.info("task_starting", thread_id=thread_id, user_id=user_id)

    try:
        async for chunk in graph.astream(
            initial_state,
            config,
            stream_mode=["messages", "updates", "custom"],
        ):
            # 事件驱动取消检查（纯内存，零 DB 开销）
            if is_task_cancelled(thread_id):
                logger.info("task_cancelled_during_execution", thread_id=thread_id)
                await cancellation_registry.cleanup(thread_id)
                return

            await dispatch_stream_chunk(pool, redis, thread_id, user_id, chunk)

        # 最终检查
        if is_task_cancelled(thread_id):
            logger.info("task_cancelled_before_finalize", thread_id=thread_id)
            await cancellation_registry.cleanup(thread_id)
            return

        # stream 正常结束 → 检查是否有 interrupt
        await finalize_task(pool, redis, graph, thread_id, user_id, config)

    except Exception as e:
        logger.exception("task_execution_error", thread_id=thread_id, error=str(e))
        # 检查是否因为被取消导致的异常
        if is_task_cancelled(thread_id):
            logger.info("task_cancelled_with_error", thread_id=thread_id)
            await cancellation_registry.cleanup(thread_id)
            return
        await persist_and_notify(pool, thread_id, user_id, {
            "type": "task.failed",
            "data": {"error": str(e), "thread_id": thread_id},
        })
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE tasks SET status='failed', updated_at=NOW() "
                "WHERE thread_id=$1 AND status='running'",
                thread_id,
            )


async def handle_resume_task(
    pool: asyncpg.Pool,
    graph,
    redis,
    persona_factory: PersonaFactory,
    data: dict,
) -> None:
    """处理恢复任务"""
    thread_id = data["thread_id"]

    # 从 resume_requests 表读取未消费的 resume value
    async with pool.acquire() as conn:
        req = await conn.fetchrow(
            "SELECT id, resume_value FROM resume_requests "
            "WHERE thread_id=$1 AND consumed=false "
            "ORDER BY created_at DESC LIMIT 1",
            thread_id,
        )
        if not req:
            logger.debug("resume_already_consumed", thread_id=thread_id)
            return  # 已被消费（幂等）

        # CAS: resuming → running
        result = await conn.execute(
            "UPDATE tasks SET status='running', updated_at=NOW() "
            "WHERE thread_id=$1 AND status='resuming'",
            thread_id,
        )
        if result == "UPDATE 0":
            logger.debug("resume_already_claimed", thread_id=thread_id)
            return

        # 标记已消费
        await conn.execute(
            "UPDATE resume_requests SET consumed=true WHERE id=$1",
            req["id"],
        )

        task = await conn.fetchrow(
            "SELECT user_id FROM tasks WHERE thread_id=$1",
            thread_id,
        )

    if not task:
        logger.error("task_not_found_for_resume", thread_id=thread_id)
        return

    user_id = task["user_id"]
    resume_value = json.loads(req["resume_value"]) if isinstance(req["resume_value"], str) else req["resume_value"]
    config = {
        "configurable": {
            "thread_id": thread_id,
            "persona_factory": persona_factory,
            "validator": None,
            "available_personas": persona_factory.list_personas(),
        }
    }

    logger.info("task_resuming", thread_id=thread_id, user_id=user_id)

    try:
        async for chunk in graph.astream(
            Command(resume=resume_value),
            config,
            stream_mode=["messages", "updates", "custom"],
        ):
            # 事件驱动取消检查（纯内存，零 DB 开销）
            if is_task_cancelled(thread_id):
                logger.info("task_cancelled_during_resume", thread_id=thread_id)
                await cancellation_registry.cleanup(thread_id)
                return

            await dispatch_stream_chunk(pool, redis, thread_id, user_id, chunk)

        # 最终检查
        if is_task_cancelled(thread_id):
            logger.info("task_cancelled_before_finalize", thread_id=thread_id)
            await cancellation_registry.cleanup(thread_id)
            return

        await finalize_task(pool, redis, graph, thread_id, user_id, config)

    except Exception as e:
        logger.exception("task_resume_error", thread_id=thread_id, error=str(e))
        # 检查是否因为被取消导致的异常
        if is_task_cancelled(thread_id):
            logger.info("task_cancelled_with_error", thread_id=thread_id)
            await cancellation_registry.cleanup(thread_id)
            return
        await persist_and_notify(pool, thread_id, user_id, {
            "type": "task.failed",
            "data": {"error": str(e), "thread_id": thread_id},
        })
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE tasks SET status='failed', updated_at=NOW() "
                "WHERE thread_id=$1",
                thread_id,
            )


# ============================================
# Orphan Recovery
# ============================================

async def recover_orphaned_tasks(
    pool: asyncpg.Pool,
    graph,
    task_queue: asyncio.Queue,
) -> None:
    """Worker 启动时扫描未完成的任务"""
    async with pool.acquire() as conn:
        orphaned = await conn.fetch(
            "SELECT thread_id, user_id, status FROM tasks "
            "WHERE status IN ('pending', 'running', 'resuming')"
        )

    for task in orphaned:
        thread_id = task["thread_id"]
        status = task["status"]

        if status == "pending":
            # 重新入队
            await task_queue.put(("new_task", json.dumps({
                "thread_id": thread_id,
            })))
            logger.info("orphan_recovered_pending", thread_id=thread_id)

        elif status == "running":
            # 上一个 Worker 崩溃留下的 → 检查 checkpoint
            config = {"configurable": {"thread_id": thread_id}}
            state = await graph.aget_state(config)

            if state.next:
                # 还有节点要执行 → 从 checkpoint 恢复
                await task_queue.put(("new_task", json.dumps({
                    "thread_id": thread_id,
                })))
                logger.info("orphan_recovered_running", thread_id=thread_id)
            else:
                # 实际上已完成 → 修正状态
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE tasks SET status='completed' "
                        "WHERE thread_id=$1",
                        thread_id,
                    )
                logger.info("orphan_fixed_completed", thread_id=thread_id)

        elif status == "resuming":
            # 有未消费的 resume → 重新入队
            await task_queue.put(("resume_task", json.dumps({
                "thread_id": thread_id,
            })))
            logger.info("orphan_recovered_resuming", thread_id=thread_id)

    if orphaned:
        logger.info("orphan_recovery_done", count=len(orphaned))


# ============================================
# Main Entry
# ============================================

async def worker_main() -> None:
    """Worker 主入口 — 独立进程"""
    config = load_config()
    database_url = os.getenv("DATABASE_URL", config.database_url)
    redis_url = os.getenv("REDIS_URL", config.redis_url)

    # Convert to asyncpg format
    dsn = database_url.replace("postgresql://", "postgres://")

    logger.info("worker_starting", database=database_url[:30] + "...")

    # 1. 初始化数据库（运行迁移）
    await init_database(database_url)

    # 2. 专用 LISTEN 连接（不占 pool）
    listen_conn = await asyncpg.connect(dsn)

    # 3. 业务查询用 pool
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)

    # 4. Redis 用于瞬态事件
    import redis.asyncio as aioredis
    redis_client = await aioredis.from_url(redis_url)

    # 5. 构建 graph
    checkpointer_cm = AsyncPostgresSaver.from_conn_string(dsn)
    checkpointer = await checkpointer_cm.__aenter__()
    await checkpointer.setup()

    # 初始化 PersonaFactory
    from core.tool_registry import ToolRegistry, init_tool_config

    init_tool_config(config)
    tool_registry = ToolRegistry()
    tool_registry.load_builtin_tools(config.tools)
    persona_factory = PersonaFactory(
        personas_config=config.personas,
        tool_registry=tool_registry,
        model_router_config=config.routing,
        litellm_url=config.litellm_url,
        litellm_master_key=config.litellm_master_key,
    )

    graph = build_boss_graph(persona_factory, checkpointer=checkpointer)

    # 6. 通知队列
    task_queue: asyncio.Queue = asyncio.Queue()

    def on_notification(conn, pid, channel, payload):
        """同步回调 — 只做入队，不做 IO"""
        task_queue.put_nowait((channel, payload))

    await listen_conn.add_listener("new_task", on_notification)
    await listen_conn.add_listener("resume_task", on_notification)
    await listen_conn.add_listener("cancel_task", on_notification)

    logger.info("worker_listening", channels=["new_task", "resume_task", "cancel_task"])

    # 7. 启动时恢复孤儿任务
    await recover_orphaned_tasks(pool, graph, task_queue)

    # 8. 主循环
    semaphore = asyncio.Semaphore(3)  # 最多 3 个并发图执行
    shutdown_event = asyncio.Event()

    def handle_shutdown(sig, frame):
        logger.info("worker_shutdown_signal", signal=sig)
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    try:
        while not shutdown_event.is_set():
            try:
                # 使用 wait_for 以便检查 shutdown 事件
                channel, payload = await asyncio.wait_for(
                    task_queue.get(),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                continue

            # cancel_task 直接处理（不需要 semaphore，纯内存操作）
            if channel == "cancel_task":
                try:
                    data = json.loads(payload)
                    await cancellation_registry.cancel(data["thread_id"])
                except Exception as e:
                    logger.exception("cancel_task_error", error=str(e))
                continue

            async def process(ch=channel, pl=payload):
                async with semaphore:
                    try:
                        data = json.loads(pl)
                        if ch == "new_task":
                            await handle_new_task(pool, graph, redis_client, persona_factory, data)
                        elif ch == "resume_task":
                            await handle_resume_task(pool, graph, redis_client, persona_factory, data)
                    except Exception as e:
                        logger.exception("worker_task_error", error=str(e))

            asyncio.create_task(process())

    finally:
        logger.info("worker_shutting_down")
        await listen_conn.remove_listener("new_task", on_notification)
        await listen_conn.remove_listener("resume_task", on_notification)
        await listen_conn.remove_listener("cancel_task", on_notification)
        await listen_conn.close()
        await pool.close()
        await redis_client.close()


def main():
    """Entry point for python -m worker.main"""
    asyncio.run(worker_main())


if __name__ == "__main__":
    main()

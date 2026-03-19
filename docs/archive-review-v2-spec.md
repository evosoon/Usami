AgenticOS LangGraph 对话基础设施重构规范 v2.0
状态: 最终修正版 | 日期: 2026-03-19
范围: Worker 驱动模型 + 前后端一体化重构
依据: LangGraph 官方文档 (2026-03-18) + 前版审计发现的 7 处认知偏离

零、工程不变式
所有后续设计必须遵守以下三条公理。违反任何一条意味着设计错误。

#	不变式	验证方法
I-1	状态的唯一真相源是 PostgreSQL，不是进程内存	任意时刻 kill -9 Worker → 重启后可恢复
I-2	事件的可靠传递 = 持久化与投递在同一因果链上	客户端断线 → 重连 → 补发 → 不丢不重
I-3	所有 mutation 必须幂等	同一请求发两次 → 效果等同发一次
一、当前实现的四个范式错误
错误 1：手动状态机模拟
位置: state.py:126, boss.py:88-102

当前实现	应该用的 LangGraph 原语
current_phase 字符串路由	图拓扑本身 + conditional_edges
hitl_pending / hitl_waiting	interrupt() + Command(resume=...)
route_next() 基于 phase 字符串	基于数据的纯函数路由
错误 2：自建事件系统
位置: boss.py:54-60, nodes.py 全文

当前实现	应该用的 LangGraph 原语
emit() 闭包 → callback → SSE	get_stream_writer() + stream_mode=["custom","messages"]
on_event callback 传参	LangGraph v2 streaming API
错误 3：孤儿任务管理
位置: routes.py:97-128

当前实现	应该用的 LangGraph 原语
asyncio.create_task(_run())	Worker 进程 + Checkpoint-resume
aupdate_state() 手动注入	Command(resume=...)
app.state.active_tasks 内存追踪	tasks 表（数据库）
错误 4：非原子性操作
位置: routes.py:266-300

aupdate_state() + asyncio.create_task() 不是原子操作
用户双击 → 两次 resume → 状态撕裂
二、修正后的完整架构
text
┌────────────────────────────────────────────────────────────────────────┐
│                          Browser (前端)                                │
│                                                                        │
│  EventSource("/api/v1/events/stream?last_seq=42")                     │
│       ↑                                                                │
│       │ SSE 双通道:                                                    │
│       │   持久化事件 (id=seq): phase.change, interrupt, task.completed │
│       │   瞬态事件 (无 id):   llm.token, heartbeat                    │
│       │                                                                │
│  POST /api/v1/tasks ──── 发起任务                                     │
│  POST /api/v1/tasks/{id}/resume ──── HiTL 恢复                        │
└──────┬─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────────────────────────────────────┐
│              FastAPI (无状态 HTTP 层 — 不持有任何长任务)                │
│                                                                        │
│  POST /tasks:                                                          │
│    1. 鉴权 (get_current_user)                                         │
│    2. 并发检查: SELECT COUNT(*) FROM tasks                             │
│       WHERE user_id=? AND status IN ('pending','running','interrupted')│
│    3. INSERT INTO tasks (thread_id, user_id, intent, status='pending') │
│    4. pg_notify('new_task', '{"thread_id":"..."}')  ← 只传 ID          │
│    5. 返回 {thread_id, status: "pending"}                              │
│                                                                        │
│  POST /tasks/{id}/resume:                                              │
│    1. CAS: UPDATE tasks SET status='resuming'                          │
│       WHERE thread_id=? AND status='interrupted'                       │
│    2. INSERT INTO resume_requests (thread_id, value, consumed=false)   │
│    3. pg_notify('resume_task', '{"thread_id":"..."}')  ← 只传 ID       │
│    4. 返回 200                                                         │
│                                                                        │
│  GET /events/stream:                                                   │
│    1. 专用连接 LISTEN events:{user_id}  ← 先建立监听                   │
│    2. 补发历史: SELECT FROM events WHERE user_id=? AND seq > last_seq   │
│    3. 消费 LISTEN queue + Redis subscribe (瞬态)                       │
│    4. seq 去重，防止补发与实时流的重叠                                  │
└──────┬──────────────────────────────┬──────────────────────────────────┘
       │ pg_notify (只传 ID，< 100B) │ LISTEN
       ▼                              ▼
┌────────────────────────────────────────────────────────────────────────┐
│              Worker 进程 (可多实例，CAS 互斥)                          │
│                                                                        │
│  启动时:                                                               │
│    1. recover_orphaned_tasks()  ← 扫描 pending/running/resuming 任务   │
│    2. 专用连接 LISTEN 'new_task', 'resume_task'                        │
│    3. 同步回调 → asyncio.Queue → 主循环消费                            │
│                                                                        │
│  run_graph(thread_id):                                                 │
│    CAS: pending → running                                              │
│    async for chunk in graph.astream(..., version="v2"):                │
│      持久化事件 → INSERT events + pg_notify(seq only)                  │
│      瞬态事件  → Redis PUBLISH                                         │
│    aget_state() → 检查 interrupts                                      │
│    有 interrupt → status = interrupted                                  │
│    无 interrupt + next 为空 → status = completed                       │
│                                                                        │
│  resume_graph(thread_id):                                              │
│    从 resume_requests 表读取 value (consumed=false)                    │
│    CAS: resuming → running                                             │
│    标记 consumed=true                                                  │
│    graph.astream(Command(resume=value), config, ...)                   │
│                                                                        │
│  并发控制: asyncio.Semaphore(N)                                        │
└──────┬─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────────────────────────────────────┐
│              PostgreSQL (唯一真相源)                                    │
│                                                                        │
│  tasks:             thread_id PK, user_id, intent, status,            │
│                     created_at, updated_at                             │
│                     status ∈ {pending, running, interrupted,           │
│                               resuming, completed, failed}             │
│                                                                        │
│  events:            seq SERIAL PK, thread_id, user_id,                │
│                     event_type, payload JSONB, created_at              │
│                                                                        │
│  resume_requests:   id SERIAL PK, thread_id, resume_value JSONB,      │
│                     consumed BOOLEAN DEFAULT false, created_at         │
│                                                                        │
│  checkpoints:       (LangGraph AsyncPostgresSaver 管理)                │
│  checkpoint_writes: (LangGraph 管理 — pending writes)                  │
└────────────────────────────────────────────────────────────────────────┘
三、LangGraph 图定义
3.1 State 设计
python
# backend/core/state.py

from __future__ import annotations
from typing import TypedDict, Annotated
import operator

def merge_task_outputs(existing: dict, new: dict) -> dict:
    """Reducer: 合并 task_outputs，不覆盖已有结果"""
    return {**existing, **new}

class BossState(TypedDict):
    # ── 核心输入 ──
    user_intent: str
    thread_id: str

    # ── Plan & Execution ──
    task_plan: TaskPlan | None
    task_outputs: Annotated[dict, merge_task_outputs]   # reducer: merge
    completed_task_ids: Annotated[list, operator.add]    # reducer: append

    # ── 结果 ──
    final_result: str | None

    # ── 追问上下文 ──
    previous_result: str | None
与旧版的差异：

删除的字段	原因
current_phase: str	图拓扑本身就是 phase，不需要手动跟踪
hitl_pending: list[HiTLRequest]	interrupt() 的 payload 就是 HiTL 请求
hitl_resolved: list[HiTLResponse]	Command(resume=...) 传入的值就是用户决定
新增 Annotated reducer：task_outputs 用 merge 语义（并行执行的多个任务结果可以安全合并），completed_task_ids 用 append 语义。

3.2 图结构
python
# backend/agents/boss.py

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

def build_boss_graph(checkpointer: AsyncPostgresSaver):
    graph = StateGraph(BossState)

    # ── 节点 ──
    graph.add_node("plan", planning_node)
    graph.add_node("validate", validate_node)
    graph.add_node("execute", execute_node)
    graph.add_node("review", review_node)        # ← 新增: interrupt 隔离层
    graph.add_node("aggregate", aggregate_node)

    # ── 边 ──
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "validate")
    graph.add_edge("validate", "execute")
    graph.add_edge("execute", "review")

    graph.add_conditional_edges("review", route_after_review, {
        "continue": "execute",    # 还有下一层 DAG
        "aggregate": "aggregate", # 全部完成
    })

    graph.add_edge("aggregate", END)

    return graph.compile(checkpointer=checkpointer)


def route_after_review(state: BossState) -> str:
    """纯函数路由 — 只看数据，不看 phase 标志"""
    plan = state.get("task_plan")
    if plan is None:
        return "aggregate"
    completed = set(state.get("completed_task_ids", []))
    ready = plan.get_ready_tasks(completed)
    return "continue" if ready else "aggregate"
关键设计：5 节点拓扑

text
START → plan → validate → execute → review → route_after_review → END
                            ↑                    │
                            └────────────────────┘  (还有 ready tasks)
                                                 │
                                            aggregate → END
为什么需要 review 节点（原计划没有）：

interrupt() 的底层机制是抛出 GraphInterrupt 异常。如果在 execute_node 内部的 asyncio.gather 中调用 interrupt()：

异常会中断 gather，取消所有并行协程
已完成的任务结果被丢弃（因为还没写入 state return）
Resume 后节点从头执行，所有 LLM 调用重跑（浪费成本）
解决方案：execute 只做纯并行执行（不含 interrupt），执行结果通过 reducer 写入 state。review 是独立节点，在 state 已安全写入后再检查是否需要 HiTL。

3.3 各节点实现
plan 节点
python
# backend/agents/nodes.py

from langgraph.config import get_stream_writer
from langgraph.types import interrupt

async def planning_node(state: BossState) -> dict:
    writer = get_stream_writer()

    # 1. 通知前端
    writer({"type": "phase.change", "data": {
        "phase": "planning", "thread_id": state["thread_id"]
    }})

    # 2. 构造 prompt
    persona_list = build_persona_list(available_personas)
    messages = build_planning_messages(
        state["user_intent"],
        persona_list,
        state.get("previous_result"),
    )

    # 3. 调用 LLM
    #    stream_mode="messages" 自动捕获 token 流 — 无需手动 emit
    response = await model_router.ainvoke(messages, model="strong")

    # 4. 解析 plan
    plan = parse_task_plan(response.content)

    if plan is None:
        # 解析失败 → interrupt 让用户决定（而非静默降级）
        # ⚠️ interrupt 前无副作用，所以重跑安全
        decision = interrupt({
            "type": "planning_failed",
            "raw_output": response.content[:2000],
            "message": "无法解析任务计划，是否使用单任务模式继续？",
            "options": ["retry", "fallback", "cancel"],
        })

        if decision["action"] == "fallback":
            plan = create_fallback_plan(state["user_intent"])
        elif decision["action"] == "cancel":
            return {"final_result": "任务已取消", "task_plan": None}
        # "retry" → interrupt resume 后节点从头执行 → 重新调用 LLM
        # 不需要额外处理

    # 5. 通知前端
    writer({"type": "phase.change", "data": {
        "phase": "planned",
        "plan_id": plan.plan_id,
        "task_count": len(plan.tasks),
        "tasks": [t.model_dump() for t in plan.tasks],
    }})

    return {"task_plan": plan}
validate 节点
python
async def validate_node(state: BossState) -> dict:
    plan = state.get("task_plan")
    if plan is None:
        return {}  # plan 被取消了，跳过

    # 纯代码校验，无 LLM（确定性 + 幂等）
    errors = PlanValidator().validate(plan)

    if errors:
        # interrupt — 让用户审查
        # ⚠️ validate 是纯函数，重跑安全
        decision = interrupt({
            "type": "validation_error",
            "errors": [e.dict() for e in errors],
            "plan": plan.model_dump(),
            "message": "任务计划校验失败，请审查",
            "options": ["approve_anyway", "cancel"],
        })

        if decision["action"] == "cancel":
            return {"final_result": "任务已取消", "task_plan": None}
        # "approve_anyway" → 继续

    # 可选：复杂计划的人工预览
    if should_require_preview(plan):
        decision = interrupt({
            "type": "plan_review",
            "plan": plan.model_dump(),
            "message": f"计划包含 {len(plan.tasks)} 个任务，请确认执行",
            "options": ["approve", "cancel"],
        })
        if decision["action"] != "approve":
            return {"final_result": "任务已取消", "task_plan": None}

    return {}
interrupt 规则遵守：

✅ interrupt 前无副作用（validate 是纯函数）
✅ interrupt 调用顺序在每次执行中保持一致（不会条件性跳过）
✅ interrupt payload 是 JSON-serializable 的 dict
✅ 不在 try/except 内调用 interrupt
execute 节点（纯并行，不含 interrupt）
python
async def execute_node(state: BossState) -> dict:
    writer = get_stream_writer()
    plan = state["task_plan"]
    if plan is None:
        return {}

    completed = set(state.get("completed_task_ids", []))
    ready_tasks = plan.get_ready_tasks(completed)

    if not ready_tasks:
        return {}  # route_after_review 会路由到 aggregate

    writer({"type": "phase.change", "data": {
        "phase": "executing",
        "round": len(completed),
        "tasks": [t.task_id for t in ready_tasks],
        "total_completed": len(completed),
        "total_tasks": len(plan.tasks),
    }})

    # ── 并行执行同一层 DAG 任务 ──
    existing_outputs = state.get("task_outputs", {})

    async def run_single_safe(task) -> tuple[str, TaskOutput]:
        """安全执行单个任务，异常在内部处理"""
        # 幂等性：如果已有结果（resume 后重跑场景），跳过
        if task.task_id in existing_outputs:
            return task.task_id, existing_outputs[task.task_id]

        writer({"type": "task.executing", "data": {
            "task_id": task.task_id,
            "persona": task.assigned_persona,
        }})

        try:
            # 构建上游上下文（信封模式）
            upstream_context = build_upstream_context(
                task, state.get("task_outputs", {})
            )

            # 执行 persona agent (ReAct)
            result = await persona_agent.ainvoke(
                build_task_input(task, upstream_context),
                {"recursion_limit": 10},
            )

            output = TaskOutput(
                task_id=task.task_id,
                summary=extract_structured_summary(result),
                full_result=result,
                confidence=1.0,
            )

            writer({"type": "task.completed_single", "data": {
                "task_id": task.task_id,
                "summary": output.summary,
            }})

            return task.task_id, output

        except Exception as e:
            output = TaskOutput(
                task_id=task.task_id,
                summary=f"执行失败: {str(e)}",
                full_result="",
                confidence=0.0,
            )

            writer({"type": "task.failed_single", "data": {
                "task_id": task.task_id,
                "error": str(e),
            }})

            return task.task_id, output

    # asyncio.gather — 并行执行，异常已在内部处理
    results = await asyncio.gather(
        *[run_single_safe(t) for t in ready_tasks]
    )

    # 收集结果
    new_outputs = {}
    new_completed = []
    for task_id, output in results:
        new_outputs[task_id] = output
        new_completed.append(task_id)

    # 通过 reducer 安全写入 state
    return {
        "task_outputs": new_outputs,          # merge_task_outputs reducer
        "completed_task_ids": new_completed,   # operator.add reducer
    }
关键设计：

execute 内部绝不调用 interrupt() — 避免与 asyncio.gather 冲突
幂等性守卫 — if task.task_id in existing_outputs: skip 确保 resume 后不重复执行
异常在 run_single_safe 内部处理 — 失败任务生成 confidence=0.0 的输出，不中断其他并行任务
用 get_stream_writer() 替代 emit() — 自定义事件通过 stream_mode="custom" 传播
review 节点（interrupt 隔离层）
python
async def review_node(state: BossState) -> dict:
    """
    检查执行结果 — 这是唯一允许在 execute 阶段触发 interrupt 的地方。
    此时 execute_node 的结果已通过 reducer 安全写入 state。
    """
    writer = get_stream_writer()
    task_outputs = state.get("task_outputs", {})

    # 检查失败的任务
    failed = [
        tid for tid, out in task_outputs.items()
        if hasattr(out, 'confidence') and out.confidence < 0.6
    ]

    if failed:
        # 安全地 interrupt — state 已持久化
        decision = interrupt({
            "type": "execution_review",
            "failed_tasks": failed,
            "failed_details": {
                tid: task_outputs[tid].summary for tid in failed
            },
            "message": f"{len(failed)} 个任务执行失败，是否继续？",
            "options": ["continue", "retry_failed", "cancel"],
        })

        if decision["action"] == "cancel":
            return {"final_result": "任务已取消"}
        elif decision["action"] == "retry_failed":
            # 从 completed_task_ids 和 task_outputs 中移除失败的
            # 注意：由于 reducer 是 append-only 的，我们需要覆写
            current_completed = [
                tid for tid in state.get("completed_task_ids", [])
                if tid not in failed
            ]
            current_outputs = {
                tid: out for tid, out in task_outputs.items()
                if tid not in failed
            }
            # ⚠️ 这里需要直接返回完整值来覆盖 reducer 累积的结果
            # 这意味着需要在 State 定义中为 retry 场景添加支持
            # MVP 简化：直接 continue，让下一轮 execute 跳过已完成的
            pass

    # 检查成本预算
    total_cost = sum(
        getattr(out, 'cost', 0) for out in task_outputs.values()
    )
    if total_cost > budget_threshold:
        decision = interrupt({
            "type": "budget_warning",
            "total_cost": total_cost,
            "threshold": budget_threshold,
            "message": "成本接近预算上限",
            "options": ["continue", "cancel"],
        })
        if decision["action"] == "cancel":
            return {"final_result": "因预算限制取消"}

    return {}  # 一切 OK，route_after_review 决定下一步
aggregate 节点
python
async def aggregate_node(state: BossState) -> dict:
    writer = get_stream_writer()
    task_outputs = state.get("task_outputs", {})

    writer({"type": "phase.change", "data": {"phase": "aggregating"}})

    # 单任务快速通道
    if len(task_outputs) == 1:
        single_output = list(task_outputs.values())[0]
        return {"final_result": single_output.full_result}

    # 多任务 LLM 汇总
    summaries = build_aggregation_context(task_outputs)

    # stream_mode="messages" 自动捕获 LLM token 流
    response = await model_router.ainvoke(
        build_aggregation_messages(state["user_intent"], summaries),
        model="strong",
    )

    writer({"type": "phase.change", "data": {"phase": "completed"}})

    return {"final_result": response.content}
四、Worker 进程
4.1 主入口
python
# backend/worker/main.py

import asyncio
import json
import asyncpg
from langgraph.types import Command

async def worker_main(dsn: str, redis_url: str):
    """Worker 主入口 — 独立进程"""

    # 1. 专用 LISTEN 连接（不占 pool）
    listen_conn = await asyncpg.connect(dsn)

    # 2. 业务查询用 pool
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)

    # 3. Redis 用于瞬态事件
    redis = await aioredis.from_url(redis_url)

    # 4. 构建 graph
    checkpointer = AsyncPostgresSaver.from_conn_string(dsn)
    await checkpointer.setup()
    graph = build_boss_graph(checkpointer)

    # 5. 通知队列
    task_queue = asyncio.Queue()

    def on_notification(conn, pid, channel, payload):
        """同步回调 — 只做入队，不做 IO"""
        task_queue.put_nowait((channel, payload))

    await listen_conn.add_listener('new_task', on_notification)
    await listen_conn.add_listener('resume_task', on_notification)

    # 6. 启动时恢复孤儿任务
    await recover_orphaned_tasks(pool, graph, task_queue)

    # 7. 主循环
    semaphore = asyncio.Semaphore(3)  # 最多 3 个并发图执行

    try:
        while True:
            channel, payload = await task_queue.get()

            async def process(ch=channel, pl=payload):
                async with semaphore:
                    try:
                        data = json.loads(pl)
                        if ch == 'new_task':
                            await handle_new_task(pool, graph, redis, data)
                        elif ch == 'resume_task':
                            await handle_resume_task(pool, graph, redis, data)
                    except Exception as e:
                        logger.exception(f"Worker error: {e}")

            asyncio.create_task(process())
    finally:
        await listen_conn.close()
        await pool.close()
        await redis.close()
4.2 任务处理
python
async def handle_new_task(pool, graph, redis, data: dict):
    thread_id = data["thread_id"]

    # CAS: pending → running（多 Worker 竞争时只有一个成功）
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE tasks SET status='running', updated_at=NOW() "
            "WHERE thread_id=$1 AND status='pending'",
            thread_id,
        )
        if result == "UPDATE 0":
            return  # 已被其他 Worker 抢到

        task = await conn.fetchrow(
            "SELECT user_id, intent FROM tasks WHERE thread_id=$1",
            thread_id,
        )

    user_id = task["user_id"]
    config = {"configurable": {"thread_id": thread_id}}
    initial_state = {
        "user_intent": task["intent"],
        "thread_id": thread_id,
    }

    try:
        async for chunk in graph.astream(
            initial_state,
            config,
            stream_mode=["messages", "updates", "custom"],
            version="v2",
        ):
            await dispatch_stream_chunk(pool, redis, thread_id, user_id, chunk)

        # stream 正常结束 → 检查是否有 interrupt
        await finalize_task(pool, redis, graph, thread_id, user_id, config)

    except Exception as e:
        await persist_and_notify(pool, thread_id, user_id, {
            "type": "task.failed",
            "data": {"error": str(e)},
        })
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE tasks SET status='failed', updated_at=NOW() "
                "WHERE thread_id=$1 AND status='running'",
                thread_id,
            )


async def handle_resume_task(pool, graph, redis, data: dict):
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
            return  # 已被消费（幂等）

        # CAS: resuming → running
        result = await conn.execute(
            "UPDATE tasks SET status='running', updated_at=NOW() "
            "WHERE thread_id=$1 AND status='resuming'",
            thread_id,
        )
        if result == "UPDATE 0":
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

    user_id = task["user_id"]
    resume_value = json.loads(req["resume_value"])
    config = {"configurable": {"thread_id": thread_id}}

    try:
        async for chunk in graph.astream(
            Command(resume=resume_value),
            config,
            stream_mode=["messages", "updates", "custom"],
            version="v2",
        ):
            await dispatch_stream_chunk(pool, redis, thread_id, user_id, chunk)

        await finalize_task(pool, redis, graph, thread_id, user_id, config)

    except Exception as e:
        await persist_and_notify(pool, thread_id, user_id, {
            "type": "task.failed",
            "data": {"error": str(e)},
        })
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE tasks SET status='failed', updated_at=NOW() "
                "WHERE thread_id=$1",
                thread_id,
            )
4.3 Stream 事件分发（双通道）
python
# 持久化事件类型
PERSISTENT_EVENTS = {
    "phase.change", "task.completed_single", "task.failed_single",
    "interrupt", "task.completed", "task.failed",
}

async def dispatch_stream_chunk(pool, redis, thread_id, user_id, chunk):
    """将 LangGraph stream chunk 分发到双通道"""

    if chunk["type"] == "messages":
        # LLM token → 瞬态通道（Redis pub/sub）
        msg, metadata = chunk["data"]
        if msg.content:
            await redis.publish(
                f"stream:{user_id}",
                json.dumps({
                    "type": "llm.token",
                    "thread_id": thread_id,
                    "content": msg.content,
                    "node": metadata.get("langgraph_node", ""),
                }),
            )

    elif chunk["type"] == "custom":
        event_data = chunk["data"]
        event_type = event_data.get("type", "custom")

        if event_type in PERSISTENT_EVENTS:
            # 持久化事件 → PostgreSQL + pg_notify
            await persist_and_notify(pool, thread_id, user_id, event_data)
        else:
            # 未知类型 → 默认瞬态
            await redis.publish(
                f"stream:{user_id}",
                json.dumps({**event_data, "thread_id": thread_id}),
            )

    elif chunk["type"] == "updates":
        # 节点完成 → 持久化（用于断线重连）
        for node_name in chunk["data"]:
            await persist_and_notify(pool, thread_id, user_id, {
                "type": "node.completed",
                "data": {"node": node_name, "thread_id": thread_id},
            })


async def finalize_task(pool, redis, graph, thread_id, user_id, config):
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
                        "data": {"value": intr.value},
                    })

            await conn.execute(
                "UPDATE tasks SET status='interrupted', updated_at=NOW() "
                "WHERE thread_id=$1",
                thread_id,
            )

        elif not state_snapshot.next:
            # 图执行完毕
            await persist_and_notify(pool, thread_id, user_id, {
                "type": "task.completed",
                "data": {"thread_id": thread_id},
            })
            await conn.execute(
                "UPDATE tasks SET status='completed', updated_at=NOW() "
                "WHERE thread_id=$1",
                thread_id,
            )
4.4 pg_notify 只传引用
python
async def persist_and_notify(pool, thread_id, user_id, event: dict):
    """持久化事件 + 轻量通知（< 100 bytes）"""
    async with pool.acquire() as conn:
        # 1. 写入 events 表（无大小限制）
        seq = await conn.fetchval(
            "INSERT INTO events (thread_id, user_id, event_type, payload) "
            "VALUES ($1, $2, $3, $4) RETURNING seq",
            thread_id, user_id, event.get("type", "unknown"),
            json.dumps(event),
        )

        # 2. pg_notify 只传 seq + type（远低于 8KB 限制）
        notification = json.dumps({
            "seq": seq,
            "type": event.get("type", "unknown"),
            "thread_id": thread_id,
        })
        await conn.execute(
            "SELECT pg_notify($1, $2)",
            f"events:{user_id}",
            notification,
        )
4.5 孤儿任务恢复
python
async def recover_orphaned_tasks(pool, graph, task_queue):
    """Worker 启动时扫描未完成的任务"""
    async with pool.acquire() as conn:
        orphaned = await conn.fetch(
            "SELECT thread_id, user_id, status FROM tasks "
            "WHERE status IN ('pending', 'running', 'resuming')"
        )

    for task in orphaned:
        if task["status"] == "pending":
            # 重新入队
            task_queue.put_nowait(("new_task", json.dumps({
                "thread_id": task["thread_id"],
            })))

        elif task["status"] == "running":
            # 上一个 Worker 崩溃留下的 → 检查 checkpoint
            config = {"configurable": {"thread_id": task["thread_id"]}}
            state = await graph.aget_state(config)

            if state.next:
                # 还有节点要执行 → 从 checkpoint 恢复
                task_queue.put_nowait(("new_task", json.dumps({
                    "thread_id": task["thread_id"],
                })))
            else:
                # 实际上已完成 → 修正状态
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE tasks SET status='completed' "
                        "WHERE thread_id=$1",
                        task["thread_id"],
                    )

        elif task["status"] == "resuming":
            # 有未消费的 resume → 重新入队
            task_queue.put_nowait(("resume_task", json.dumps({
                "thread_id": task["thread_id"],
            })))
五、SSE Endpoint（正确的时序协议）
python
# backend/api/sse.py

from sse_starlette.sse import EventSourceResponse

@router.get("/events/stream")
async def stream_events(
    request: Request,
    last_seq: int = Query(0),           # 前端主动传（刷新页面场景）
    thread_id: str | None = Query(None), # 可选：只订阅特定线程
    user: UserProfile = Depends(get_current_user),
):
    # 优先用 SSE 规范的 Last-Event-ID（自动重连场景）
    header_last_id = request.headers.get("Last-Event-ID")
    effective_last_seq = int(header_last_id) if header_last_id else last_seq

    async def event_generator():
        queue = asyncio.Queue(maxsize=200)  # 背压

        # ══ Phase 1: 先 LISTEN（确保不漏通知） ══
        listen_conn = await asyncpg.connect(dsn)
        channel = f"events:{user.id}"

        def on_pg_notify(conn, pid, ch, payload):
            try:
                queue.put_nowait(("pg", payload))
            except asyncio.QueueFull:
                logger.warning(f"SSE queue full for user {user.id}")

        await listen_conn.add_listener(channel, on_pg_notify)

        # Redis 订阅（瞬态事件）
        redis_sub = redis.pubsub()
        await redis_sub.subscribe(f"stream:{user.id}")

        async def redis_reader():
            async for message in redis_sub.listen():
                if message["type"] == "message":
                    try:
                        queue.put_nowait(("redis", message["data"]))
                    except asyncio.QueueFull:
                        pass  # 瞬态事件丢了就丢了

        redis_task = asyncio.create_task(redis_reader())

        try:
            # ══ Phase 2: 补发历史（LISTEN 已经在接收新通知） ══
            async with pool.acquire() as conn:
                if thread_id:
                    missed = await conn.fetch(
                        "SELECT seq, event_type, payload FROM events "
                        "WHERE user_id=$1 AND thread_id=$2 AND seq > $3 "
                        "ORDER BY seq",
                        user.id, thread_id, effective_last_seq,
                    )
                else:
                    missed = await conn.fetch(
                        "SELECT seq, event_type, payload FROM events "
                        "WHERE user_id=$1 AND seq > $2 ORDER BY seq",
                        user.id, effective_last_seq,
                    )

            last_sent_seq = effective_last_seq
            for evt in missed:
                yield {
                    "id": str(evt["seq"]),
                    "event": evt["event_type"],
                    "data": evt["payload"],  # 已经是 JSON 字符串
                }
                last_sent_seq = evt["seq"]

            # ══ Phase 3: 消费实时流 ══
            while not await request.is_disconnected():
                try:
                    source, payload_str = await asyncio.wait_for(
                        queue.get(), timeout=30
                    )

                    if source == "pg":
                        # 持久化事件通知
                        meta = json.loads(payload_str)

                        # 去重：跳过补发阶段已发过的
                        if meta["seq"] <= last_sent_seq:
                            continue

                        # 可选 thread_id 过滤
                        if thread_id and meta.get("thread_id") != thread_id:
                            continue

                        # 从 DB 读完整事件
                        async with pool.acquire() as conn:
                            event = await conn.fetchrow(
                                "SELECT event_type, payload FROM events "
                                "WHERE seq=$1",
                                meta["seq"],
                            )

                        if event:
                            yield {
                                "id": str(meta["seq"]),
                                "event": event["event_type"],
                                "data": event["payload"],
                            }
                            last_sent_seq = meta["seq"]

                    elif source == "redis":
                        # 瞬态事件 — 无 id，不持久化
                        event_data = json.loads(payload_str)

                        # 可选 thread_id 过滤
                        if thread_id and event_data.get("thread_id") != thread_id:
                            continue

                        yield {
                            "event": event_data.get("type", "custom"),
                            "data": payload_str,
                        }

                except asyncio.TimeoutError:
                    yield {"event": "keepalive", "data": ""}

        finally:
            redis_task.cancel()
            await redis_sub.unsubscribe()
            await listen_conn.remove_listener(channel, on_pg_notify)
            await listen_conn.close()

    return EventSourceResponse(event_generator())
时序保证：

text
T0: LISTEN events:{user_id}          ← 先监听
T1: SELECT events WHERE seq > 42     ← 再查历史
T2: yield events [43, 44, 45]        ← 补发
T3: Worker 产生 event 46, pg_notify  ← 通知进入 queue
T4: queue.get() → meta.seq=46 > 45  ← 实时推送（不漏）
T5: 如果 T3 发生在 T0-T1 之间:
    → 通知已在 queue 中
    → 且 46 也在 SELECT 结果中
    → last_sent_seq 去重 → 不重复发送
六、HTTP API
6.1 创建任务
python
# backend/api/routes.py

@router.post("/tasks", response_model=TaskCreatedResponse)
async def create_task(
    req: CreateTaskRequest,
    user: UserProfile = Depends(get_current_user),
):
    # 1. 并发检查（数据库，不是内存）
    async with pool.acquire() as conn:
        active_count = await conn.fetchval(
            "SELECT COUNT(*) FROM tasks "
            "WHERE user_id=$1 AND status IN ('pending','running','interrupted','resuming')",
            user.id,
        )
        if active_count >= 3:
            raise HTTPException(429, "Too many active tasks")

        # 2. 创建任务记录
        thread_id = f"thread_{uuid4().hex[:12]}"
        await conn.execute(
            "INSERT INTO tasks (thread_id, user_id, intent, status) "
            "VALUES ($1, $2, $3, 'pending')",
            thread_id, user.id, req.intent,
        )

        # 3. 持久化创建事件
        seq = await conn.fetchval(
            "INSERT INTO events (thread_id, user_id, event_type, payload) "
            "VALUES ($1, $2, 'task.created', $3) RETURNING seq",
            thread_id, user.id,
            json.dumps({"type": "task.created", "data": {
                "thread_id": thread_id, "intent": req.intent
            }}),
        )

        # 4. pg_notify Worker（只传 ID）
        await conn.execute(
            "SELECT pg_notify('new_task', $1)",
            json.dumps({"thread_id": thread_id}),
        )

    return {"thread_id": thread_id, "status": "pending"}
6.2 HiTL 恢复
python
@router.post("/tasks/{thread_id}/resume")
async def resume_task(
    thread_id: str,
    req: ResumeRequest,
    user: UserProfile = Depends(get_current_user),
):
    async with pool.acquire() as conn:
        # 1. 权限检查
        task = await conn.fetchrow(
            "SELECT user_id, status FROM tasks WHERE thread_id=$1",
            thread_id,
        )
        if not task:
            raise HTTPException(404)
        if task["user_id"] != user.id:
            raise HTTPException(403)

        # 2. CAS: interrupted → resuming
        result = await conn.execute(
            "UPDATE tasks SET status='resuming', updated_at=NOW() "
            "WHERE thread_id=$1 AND status='interrupted'",
            thread_id,
        )
        if result == "UPDATE 0":
            raise HTTPException(
                409,
                f"Task is '{task['status']}', not 'interrupted'"
            )

        # 3. 持久化 resume 请求（Worker 崩溃后可恢复）
        await conn.execute(
            "INSERT INTO resume_requests (thread_id, resume_value) "
            "VALUES ($1, $2)",
            thread_id,
            json.dumps({"action": req.action, "data": req.data}),
        )

        # 4. pg_notify Worker（加速器，非可靠性保证）
        await conn.execute(
            "SELECT pg_notify('resume_task', $1)",
            json.dumps({"thread_id": thread_id}),
        )

    return {"status": "resuming"}
七、数据库迁移
sql
-- alembic/versions/xxx_refactor_v2.py

-- 1. tasks 表
CREATE TABLE IF NOT EXISTS tasks (
    thread_id   VARCHAR(64) PRIMARY KEY,
    user_id     VARCHAR(64) NOT NULL,
    intent      TEXT NOT NULL,
    status      VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','running','interrupted','resuming','completed','failed')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tasks_user_status ON tasks (user_id, status);
CREATE INDEX idx_tasks_status ON tasks (status);

-- 2. events 表
CREATE TABLE IF NOT EXISTS events (
    seq         SERIAL PRIMARY KEY,
    thread_id   VARCHAR(64) NOT NULL,
    user_id     VARCHAR(64) NOT NULL,
    event_type  VARCHAR(64) NOT NULL,
    payload     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_events_user_seq ON events (user_id, seq);
CREATE INDEX idx_events_thread_seq ON events (thread_id, seq);

-- 3. resume_requests 表
CREATE TABLE IF NOT EXISTS resume_requests (
    id            SERIAL PRIMARY KEY,
    thread_id     VARCHAR(64) NOT NULL REFERENCES tasks(thread_id),
    resume_value  JSONB NOT NULL,
    consumed      BOOLEAN NOT NULL DEFAULT false,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_resume_thread ON resume_requests (thread_id, consumed);
八、前端适配
8.1 事件类型映射
旧事件	新事件	说明
task.planning	phase.change {phase:"planning"}	统一为 phase.change
task.planning_chunk	llm.token {node:"plan"}	LangGraph messages 模式自动捕获
task.plan_ready	phase.change {phase:"planned", tasks:[...]}	合并 plan 数据
hitl.request	interrupt {type:"...", value:{...}}	LangGraph interrupt payload
task.executing {task_id}	task.executing {task_id, persona}	保持，通过 custom stream
task.progress {status}	task.completed_single / task.failed_single	更明确的语义
task.result_chunk	llm.token {node:"aggregate"}	LangGraph messages 模式
task.completed	task.completed + phase.change {phase:"completed"}	保持
8.2 Thread Store 核心变更
typescript
// frontend/src/stores/thread-store.ts

// 新增: 按 node 区分的 streaming 文本
interface ThreadStreamState {
  planningText: string;     // node === "plan"
  aggregateText: string;    // node === "aggregate"
  activeNode: string;       // 当前活跃节点
}

// 事件处理
function handleSSEEvent(event: SSEEvent) {
  switch (event.type) {
    case "llm.token":
      // 按 node 字段区分 token 来源
      if (event.data.node === "plan") {
        thread.planningText += event.data.content;
      } else if (event.data.node === "aggregate") {
        thread.aggregateText += event.data.content;
      }
      break;  // 瞬态事件不 append 到 events 列表

    case "phase.change":
      thread.phase = event.data.phase;
      if (event.data.tasks) {
        thread.taskPlan = event.data.tasks;
      }
      if (event.data.total_tasks) {
        thread.progress = {
          completed: event.data.total_completed,
          total: event.data.total_tasks,
        };
      }
      break;

    case "interrupt":
      thread.phase = "hitl_waiting";
      thread.pendingInterrupt = event.data.value;
      break;

    case "task.completed":
      thread.phase = "completed";
      break;

    default:
      // 其他持久化事件 append 到 events 列表
      thread.events.push(event);
  }
}
8.3 SSE 连接配置
typescript
// frontend/src/lib/sse.ts

function createSSEConnection(userId: string, lastSeq: number, threadId?: string) {
  const params = new URLSearchParams({ last_seq: String(lastSeq) });
  if (threadId) params.set("thread_id", threadId);

  const url = `/api/v1/events/stream?${params}`;
  const source = new EventSource(url);

  // Last-Event-ID 在自动重连时由浏览器自动发送
  // last_seq query param 是刷新页面时的 fallback

  source.addEventListener("llm.token", (e) => {
    handleSSEEvent({ type: "llm.token", data: JSON.parse(e.data) });
  });

  source.addEventListener("phase.change", (e) => {
    const event = { type: "phase.change", data: JSON.parse(e.data), seq: Number(e.lastEventId) };
    handleSSEEvent(event);
  });

  source.addEventListener("interrupt", (e) => {
    const event = { type: "interrupt", data: JSON.parse(e.data), seq: Number(e.lastEventId) };
    handleSSEEvent(event);
  });

  // ... 其他事件类型

  return source;
}
九、Docker Compose
yaml
# docker-compose.yml 新增

services:
  # ... 现有 api, postgres, redis ...

  worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    command: python -m worker.main
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
    deploy:
      replicas: 1  # MVP 单实例，可扩展为多实例
    restart: unless-stopped
十、完整文件变更清单
后端
文件	变更	说明
backend/core/state.py	重写	TypedDict + Annotated reducers；删除 current_phase, hitl_pending, hitl_resolved
backend/core/models.py	新建	tasks, events, resume_requests 表的 SQLAlchemy/asyncpg 模型
backend/core/task_queue.py	新建	pg_notify 辅助函数（只传 ID）
backend/core/hitl.py	简化	仅保留 should_require_preview(), PlanValidator；删除 HiTLGateway
backend/agents/boss.py	重写	5 节点拓扑；删除 route_next, emit, on_event
backend/agents/nodes.py	重写	interrupt() + get_stream_writer()；新增 review_node
backend/api/routes.py	重写	POST /tasks 只写 DB + notify；POST /resume 用 CAS + resume_requests
backend/api/sse.py	重写	双通道 (pg LISTEN + Redis sub)；先 LISTEN 后查询；seq 去重
backend/main.py	简化	删除 sse_event_callback, active_tasks, sse_manager 初始化
backend/worker/__init__.py	新建	-
backend/worker/main.py	新建	Worker 主入口；LISTEN 循环；stream dispatch
backend/worker/Dockerfile	新建	Worker 容器
backend/alembic/versions/xxx_refactor_v2.py	新建	tasks + events + resume_requests 迁移
前端
文件	变更	说明
frontend/src/types/sse.ts	修改	新增 llm.token, phase.change, interrupt 类型定义
frontend/src/stores/thread-store.ts	修改	按 node 区分 streaming；统一 phase 管理
frontend/src/hooks/use-derived-messages.ts	修改	根据 node 字段区分 token 来源
frontend/src/lib/sse.ts	修改	last_seq query param；分事件类型注册 listener
部署
文件	变更	说明
docker-compose.yml	修改	新增 worker 服务
十一、风险与缓解
#	风险	缓解策略
R1	interrupt() 节点重跑导致 LLM 重复调用	execute_node 幂等守卫：检查 existing_outputs 跳过已完成任务
R2	pg_notify 丢失（无 LISTEN 时）	Worker 启动时 recover_orphaned_tasks() 扫描 pending/running/resuming
R3	多 Worker 竞争同一任务	CAS: UPDATE ... WHERE status='pending'，rowcount=0 则放弃
R4	SSE 补发与实时流的竞态	先 LISTEN 后查询 + last_sent_seq 去重
R5	pg_notify payload 超 8KB	notify 只传 seq/ID（<100B），完整事件走 events 表
R6	asyncpg LISTEN 连接断开	add_termination_listener 检测断开 → 自动重建连接
R7	LLM token 高频 → Redis 压力	Worker 端 token 节流：每 200ms 或 10 token 合并一次
R8	review_node 中 retry_failed 需要覆写 reducer 累积值	MVP 简化：retry_failed 暂不实现，只支持 continue/cancel
十二、执行顺序
text
Step 1: 数据库迁移
  └── alembic/versions/xxx_refactor_v2.py
  └── 验证: psql \d tasks; \d events; \d resume_requests;

Step 2: 后端核心层
  ├── core/state.py (BossState TypedDict)
  ├── core/models.py (表模型)
  └── core/task_queue.py (pg_notify helpers)

Step 3: LangGraph 图重建
  ├── agents/boss.py (5 节点拓扑)
  ├── agents/nodes.py (interrupt + stream_writer)
  └── 验证: 单元测试 happy path + interrupt/resume

Step 4: Worker 进程
  ├── worker/main.py
  └── 验证: pg_notify → Worker 消费 → events 写入

Step 5: HTTP API 重写
  ├── api/routes.py (POST /tasks, POST /resume)
  └── 验证: curl 测试 → 检查 tasks 表状态流转

Step 6: SSE Endpoint
  ├── api/sse.py (双通道 + 断线重连)
  └── 验证: EventSource 连接 → 断开 → 重连 → 补发

Step 7: 前端适配
  ├── types/sse.ts
  ├── stores/thread-store.ts
  ├── hooks/use-derived-messages.ts
  └── lib/sse.ts

Step 8: Docker + 集成测试
  ├── docker-compose.yml (worker 服务)
  └── E2E: 完整任务流 + HiTL 中断恢复 + 断线重连

Step 9: 清理旧代码
  ├── 删除 emit() 闭包体系
  ├── 删除 route_next()
  ├── 删除 asyncio.create_task(_run())
  ├── 删除 aupdate_state() 手动注入
  ├── 删除 app.state.active_tasks
  └── 删除 HiTLGateway (保留 PlanValidator)
十三、验证 Checklist
#	场景	预期	对应不变式
✅ 1	Happy path: 用户发起任务 → 规划 → 执行 → 汇总 → 完成	events 表有完整记录；tasks.status = completed	I-1
✅ 2	Worker 在 execute 阶段 kill -9 → 重启	从 checkpoint 恢复，已完成任务不重跑	I-1
✅ 3	Validate 触发 interrupt → 用户 approve → 继续	tasks: running → interrupted → resuming → running → completed	I-3
✅ 4	用户双击 resume 按钮	第二次 409 Conflict（CAS 保证）	I-3
✅ 5	SSE 断线 → 重连 (Last-Event-ID: 42)	补发 seq > 42 的所有持久化事件，瞬态事件不补发	I-2
✅ 6	刷新页面 → 重新建立 SSE 连接	last_seq query param 补发	I-2
✅ 7	两个 Worker 同时收到 new_task 通知	CAS 保证只有一个执行	I-3
✅ 8	Plan 解析失败	interrupt 通知用户（不静默降级）	—
✅ 9	并行 DAG: 3 个任务并行，1 个失败	review_node interrupt；另 2 个结果已保存	—
✅ 10	pg_notify 发出时无 Worker LISTEN	Worker 重启后 recover_orphaned_tasks 补偿	I-1

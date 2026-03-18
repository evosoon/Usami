
# AgenticOS 对话基础设施：从第一性原理重建

## 问题的本质

你现在的 MVP 不是"有 bug"——而是**用错了范式**。你用了 LangGraph 的壳，但内核是一套手写的"状态机模拟"。这就像买了一台数控机床，然后把它当桌子用手锯木头。

具体来说：

| 你手动实现的 | LangGraph 已经提供的原语 |
|---|---|
| `current_phase` 字符串路由 | `conditional_edges` + 节点拓扑本身 |
| `hitl_pending` / `hitl_waiting` | `interrupt()` + `Command(resume=...)` |
| `emit()` 闭包 → SSE | `get_stream_writer()` + `stream_mode=["custom", "messages", "updates"]` |
| `asyncio.create_task(_run())` | Checkpoint-resume 本身就是持久化的任务恢复机制 |
| `aupdate_state()` 手动注入 | `graph.invoke(Command(resume=...), config)` |

**你在 LangGraph 之上重建了一个 LangGraph。** 这不是代码问题，是认知问题。下面我从第一性原理出发，重建整套工程认知。

---

## 一、三条不可违背的工程不变式

在讨论任何具体实现之前，必须先确立三条不变式。它们不是"最佳实践"——它们是**所有后续设计的公理**。

### 不变式 1：状态的唯一真相源是数据库，不是进程内存

```
❌ 你现在的模型:

  HTTP 请求 → asyncio.create_task() → 进程内存中跑状态机
                                        ↓
                                 进程重启 = 全部丢失

✅ 正确的模型:

  HTTP 请求 → 写入 PostgreSQL (task record) → 返回
                        ↓
  Worker (可以是同进程的事件循环，也可以是独立进程)
    ↓
  从 PostgreSQL 读取 pending task → LangGraph.invoke(config={thread_id})
    ↓
  LangGraph Checkpointer → 每个节点执行完 → 自动写 PostgreSQL
    ↓
  进程崩溃? → Worker 重启 → 从 checkpoint 恢复 → 继续执行
```

**为什么这是不变式？** 因为你的系统是 cloud-native + Docker 部署。容器随时可能被调度器杀掉（OOM、滚动更新、节点漂移）。任何存在于进程内存中、不在数据库中的状态，都是**幻觉**。

### 不变式 2：事件的可靠传递 = 持久化 + 投递 是原子的

```
❌ 你现在的模型:

  emit() → persist_event(INSERT) → broadcast(Redis pub/sub)
                                    ↓
                              这两步不是原子的
                              中间崩溃 = 事件已入库但用户永远看不到

✅ 正确的模型 (Transactional Outbox):

  LangGraph 节点内:
    get_stream_writer()({type: "task.planning", data: ...})
        ↓
  LangGraph stream → FastAPI SSE endpoint → 浏览器

  事件持久化:
    利用 LangGraph 的 checkpoint 本身（它已经在每个节点后写 PostgreSQL）
    + 额外写 events 表 (在同一个事务内，或者直接从 checkpoint diff 派生)
        ↓
  断线重连:
    GET /events/stream?last_seq=42
    → 从 events 表读 seq > 42 的所有事件
    → 补发给客户端
    → 然后切换到实时流
```

**为什么这是不变式？** 因为你的系统承诺是"用户能看到每一步发生了什么"。如果用户刷新页面后丢失了中间状态，这个承诺就是假的。

### 不变式 3：中断和恢复必须是幂等的

```
❌ 你现在的模型:

  POST /hitl → aupdate_state() → create_task(ainvoke())
  用户双击 → 两次 aupdate_state → 两个 ainvoke 并行 → 状态撕裂

✅ 正确的模型:

  POST /hitl → 幂等性检查 (数据库锁 or 状态检查) →
    graph.invoke(Command(resume=value), config)
        ↓
  LangGraph 内部的 interrupt/resume 机制保证:
  - resume 只消费一次 interrupt
  - 同一个 interrupt 多次 resume 只有第一次生效（幂等）
  - 节点从头重跑（interrupt 规则），所以 interrupt 前的代码必须幂等
```

**为什么这是不变式？** 因为网络是不可靠的。用户会双击、浏览器会重试、负载均衡器会重发。任何 non-idempotent 的 mutation 操作在分布式环境中都是定时炸弹。

---

## 二、正确理解 LangGraph 的运行时模型

你对 LangGraph 的使用停留在"图定义"层面——定义了节点和边。但 LangGraph 的真正价值在于它的**运行时语义**。让我完整拆解：

### 2.1 Checkpoint 不是"日志"——它是可恢复的计算快照

```
                    Checkpoint 的语义模型
                    
graph.invoke(input, config={thread_id: "t1"})
    │
    ▼  START → node_1
    │  ┌─────────────────────────────┐
    │  │ node_1 执行                  │
    │  │ 返回 state updates           │
    │  └─────────────────────────────┘
    │         │
    │         ▼  Checkpointer 写入 (自动)
    │  ┌─────────────────────────────────────────┐
    │  │ checkpoint_1 = {                        │
    │  │   thread_id: "t1",                      │
    │  │   checkpoint_id: "cp_abc",              │
    │  │   channel_values: {完整 state 快照},     │
    │  │   pending_writes: [],                   │
    │  │   parent_checkpoint_id: "cp_000",       │
    │  │   metadata: {source: "loop", step: 1}   │
    │  │ }                                       │
    │  └─────────────────────────────────────────┘
    │         │
    │         ▼  node_2 执行...
    │         ▼  checkpoint_2 写入...
    │
    ▼  进程崩溃 💥
    
    ... 进程重启 ...
    
graph.invoke(None, config={thread_id: "t1"})
    │
    ▼  Checkpointer 读取最新 checkpoint
    │  → 恢复到 node_2 完成后的状态
    │  → 从 node_3 继续执行
    │
    ▼  这就是"crash recovery"的真正语义
```

**关键洞察**：`AsyncPostgresSaver` 你已经在用了，但你绕过了它的 resume 能力，自己用 `asyncio.create_task` 管理生命周期——这等于有了银行保险柜但把钱藏在床垫下面。

### 2.2 `interrupt()` 不是"设置一个标志"——它是协程挂起

LangGraph 的 `interrupt()` 是通过**抛异常**实现的（类似 Python 的 `GeneratorExit`）：

```python
# LangGraph 内部语义（简化）

def interrupt(value):
    """挂起当前节点，把 value 传给调用方"""
    raise GraphInterrupt(value)  
    # 运行时捕获这个异常 → 写 checkpoint → 返回给调用方

# 在你的节点里：
async def validate_node(state):
    errors = validator.validate(state["task_plan"])
    if errors:
        # ⬇️ 这一行会：
        # 1. 抛出 GraphInterrupt
        # 2. LangGraph 运行时捕获它
        # 3. 写入 checkpoint（含 interrupt payload）
        # 4. 返回给调用方（stream 会产生 interrupt 事件）
        decision = interrupt({
            "type": "validation_error",
            "errors": errors,
            "plan": state["task_plan"]
        })
        # ⬇️ 这行代码在 resume 时才执行
        # decision 就是 Command(resume=...) 传入的值
        if decision["action"] == "approve_anyway":
            return {**state}  # 继续
        elif decision["action"] == "reject":
            return {**state, "aborted": True}

# 恢复时：
graph.invoke(
    Command(resume={"action": "approve_anyway"}),
    config={"configurable": {"thread_id": "t1"}}
)
# → LangGraph 从 checkpoint 恢复
# → 重新执行 validate_node（从头开始！）
# → 遇到 interrupt() 时，发现有 resume 值
# → interrupt() 返回 resume 值（不再抛异常）
# → 节点继续执行
```

**你现在的实现 vs 正确实现的对比**：

```
❌ 你现在做的:

validate_node:
  if errors:
    hitl_gateway._create_request(ERROR)
    emit("hitl.request")
    return {current_phase: "hitl_waiting"}  ← 手动设标志

route_next:
  if current_phase == "hitl_waiting": → END

恢复 API:
  aupdate_state(config, {hitl_resolved, current_phase: source_phase})
  create_task(ainvoke(None, config))  ← 手动恢复

问题:
1. route_next 只能在节点边界路由，不能在节点内部暂停
2. 手动管理 current_phase 是脆弱的（字符串枚举、容易写错）
3. aupdate_state + ainvoke 不是原子的
4. create_task 是孤儿任务

✅ 应该做的:

validate_node:
  if errors:
    decision = interrupt({"type": "error", "errors": errors})
    # ← LangGraph 处理一切：checkpoint、suspend、resume

恢复 API:
  graph.invoke(
    Command(resume={"action": "approve"}),
    config={"configurable": {"thread_id": thread_id}}
  )
  # ← 一行代码。原子性。幂等性。由框架保证。

好处:
1. 没有 current_phase 状态机 —— 图拓扑本身就是状态机
2. 没有 hitl_pending / hitl_resolved —— interrupt payload 就是
3. 没有 aupdate_state —— Command(resume=) 是唯一的恢复路径
4. 没有 asyncio.create_task —— invoke 本身就是同步/异步可选的
```

### 2.3 Streaming v2 替代你的 emit() 体系

你现在的 emit 体系：

```python
# 你的实现:
def build_boss_graph(on_event):
    def emit(event_type, data=None):
        on_event(event_type, data)  # → callback → persist → broadcast → SSE
    
    async def planning_node(state):
        emit("task.planning")
        for chunk in model.astream(...):
            emit("task.planning_chunk", {"chunk": chunk})
        ...
```

LangGraph 已经有了更好的原语：

```python
# 正确的实现:
from langgraph.config import get_stream_writer

async def planning_node(state):
    writer = get_stream_writer()
    
    # 自定义事件 → stream_mode="custom" 消费
    writer({"type": "task.planning", "data": {"phase": "started"}})
    
    # LLM token 流 → stream_mode="messages" 自动捕获（无需手动 emit）
    response = await model.ainvoke(messages)  
    # ↑ 即使用 invoke 而非 stream，messages 模式也能捕获 token
    
    writer({"type": "task.plan_ready", "data": {"plan_id": plan.plan_id}})
    return {"task_plan": plan}

# FastAPI SSE endpoint:
@app.get("/api/v1/tasks/{thread_id}/stream")
async def stream_task(thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    
    async def event_generator():
        async for chunk in graph.astream(
            None,  # resume from checkpoint
            config,
            stream_mode=["messages", "updates", "custom"],
            version="v2",
        ):
            if chunk["type"] == "messages":
                msg, meta = chunk["data"]
                yield format_sse("llm.token", {"content": msg.content, "node": meta["langgraph_node"]})
            
            elif chunk["type"] == "custom":
                yield format_sse(chunk["data"]["type"], chunk["data"].get("data"))
            
            elif chunk["type"] == "updates":
                for node_name, state_update in chunk["data"].items():
                    yield format_sse("node.completed", {"node": node_name})
    
    return EventSourceResponse(event_generator())
```

**关键区别**：
- 你不再需要 `emit()` 闭包、`on_event` callback、`sse_event_callback`
- LLM token 流是**自动的**——`stream_mode="messages"` 会捕获所有节点内的 LLM 调用
- 自定义事件用 `get_stream_writer()` 发送，通过 `stream_mode="custom"` 接收
- 图的节点级生命周期事件用 `stream_mode="updates"` 自动获取

---

## 三、重建后的完整架构

基于以上三条不变式和 LangGraph 原语的正确使用，这是重建后的架构：

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        用户浏览器                                       │
│                                                                         │
│  EventSource("/api/v1/tasks/{thread_id}/stream?last_seq=0")            │
│       ↑                                                                 │
│       │ SSE: llm.token, node.completed, task.plan_ready, interrupt, ... │
│       │                                                                 │
│  POST /api/v1/tasks ──── 发起任务                                      │
│  POST /api/v1/tasks/{id}/resume ──── HiTL 恢复                         │
│  POST /api/v1/tasks/{id}/message ──── 追问                             │
└──────┬───────────────────────────────┬──────────────────────────────────┘
       │                               │
       ▼                               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     FastAPI (无状态 HTTP 层)                             │
│                                                                          │
│  POST /tasks:                                                            │
│    1. 鉴权                                                               │
│    2. INSERT INTO tasks (thread_id, user_id, intent, status='pending')   │
│    3. 返回 {thread_id, status: "pending"}                                │
│    ← 注意: 不启动任何后台任务                                             │
│                                                                          │
│  GET /tasks/{id}/stream:                                                 │
│    1. 补发历史事件 (SELECT FROM events WHERE seq > last_seq)              │
│    2. 启动 graph.astream() 或 订阅实时流                                  │
│    3. 持续 SSE 推送                                                      │
│                                                                          │
│  POST /tasks/{id}/resume:                                                │
│    1. 幂等性检查 (task.status == 'interrupted')                           │
│    2. UPDATE tasks SET status = 'running'                                │
│    3. graph.invoke(Command(resume=value), config)                        │
│       ← 同步执行！由 SSE endpoint 流式输出                                │
│       或 推入执行队列                                                     │
└──────────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     LangGraph Runtime                                    │
│                                                                          │
│  StateGraph 定义:                                                        │
│                                                                          │
│    START ──► plan ──► validate ──► execute ──► aggregate ──► END         │
│                          │            ↻                                   │
│                       interrupt()   (自循环: DAG 分层)                    │
│                          │                                               │
│                    checkpoint 写入                                        │
│                    等待 Command(resume=)                                  │
│                                                                          │
│  Checkpointer: AsyncPostgresSaver                                        │
│    → 每个节点执行后自动写 PostgreSQL                                       │
│    → crash recovery: 从最新 checkpoint 恢复                               │
│                                                                          │
│  Streaming:                                                              │
│    → messages: LLM token 流 (自动捕获)                                   │
│    → custom: 节点内 get_stream_writer() 发送的自定义事件                   │
│    → updates: 节点完成通知                                                │
└──────────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     PostgreSQL (唯一真相源)                               │
│                                                                          │
│  tasks 表:                                                               │
│    thread_id PK, user_id, intent, status, created_at, updated_at         │
│    status: pending → running → interrupted → running → completed/failed  │
│                                                                          │
│  checkpoints 表 (LangGraph 管理):                                        │
│    thread_id, checkpoint_id, channel_values (JSONB), parent_id, ...      │
│                                                                          │
│  events 表 (用于断线重连补发):                                             │
│    seq SERIAL PK, thread_id, event_type, data JSONB, created_at          │
│                                                                          │
│  NOTIFY 机制:                                                             │
│    events INSERT trigger → pg_notify('events:{thread_id}', seq::text)    │
│    → asyncpg LISTEN → SSE broadcaster                                    │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 四、逐节点重建——图的正确定义

### 4.1 State 设计：去掉所有手动路由字段

```python
# ❌ 你现在的 state:
state = {
    "user_intent": str,
    "thread_id": str,
    "current_phase": str,        # ← 删除：图拓扑本身就是 phase
    "task_plan": TaskPlan,
    "task_outputs": dict,
    "completed_task_ids": list,
    "hitl_pending": list,        # ← 删除：interrupt() 管理
    "previous_result": str,
}

# ✅ 正确的 state:
from typing import TypedDict, Annotated
from langgraph.graph import add_messages
import operator

class BossState(TypedDict):
    # 核心输入
    user_intent: str
    thread_id: str
    
    # Plan & Execution
    task_plan: TaskPlan | None
    task_outputs: Annotated[dict, merge_task_outputs]  # ← reducer 函数
    completed_task_ids: Annotated[list, operator.add]   # ← append-only
    
    # 结果
    final_result: str | None
    
    # 追问上下文
    previous_result: str | None

def merge_task_outputs(existing: dict, new: dict) -> dict:
    """Reducer: 合并 task_outputs，不覆盖"""
    return {**existing, **new}
```

**关键改变**：
1. **删除 `current_phase`**：你不需要手动跟踪"我在哪个阶段"——LangGraph 的图拓扑 + checkpoint 自动知道。
2. **删除 `hitl_pending`**：`interrupt()` 的 payload 就是 HiTL 请求的内容。
3. **使用 Annotated + reducer**：`task_outputs` 和 `completed_task_ids` 使用 reducer 函数，支持并行节点安全写入。

### 4.2 图定义：让拓扑做路由，不是字符串

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

def build_boss_graph(checkpointer):
    graph = StateGraph(BossState)
    
    # 节点
    graph.add_node("plan", planning_node)
    graph.add_node("validate", validate_node)
    graph.add_node("execute", execute_node)
    graph.add_node("aggregate", aggregate_node)
    
    # 边 —— 拓扑本身就是流程控制
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "validate")
    
    # validate → execute（无条件，因为 interrupt 会在节点内部暂停）
    graph.add_edge("validate", "execute")
    
    # execute 的自循环：还有任务要执行吗？
    graph.add_conditional_edges("execute", should_continue_executing, {
        "continue": "execute",      # 还有下一层 DAG
        "aggregate": "aggregate",   # 全部完成
    })
    
    graph.add_edge("aggregate", END)
    
    return graph.compile(checkpointer=checkpointer)

def should_continue_executing(state: BossState) -> str:
    """纯函数路由——不需要 current_phase"""
    plan = state["task_plan"]
    completed = set(state["completed_task_ids"])
    ready = plan.get_ready_tasks(completed)
    
    if ready:
        return "continue"
    return "aggregate"
```

**注意看什么消失了**：
- 没有 `route_next()` —— 每个条件边有自己的路由函数
- 没有 `current_phase` 字符串比较 —— 路由逻辑是纯函数，基于数据而非标志
- 没有 `hitl_waiting → END` —— `interrupt()` 在节点内部暂停，不需要路由到 END

### 4.3 planning_node：用 stream_writer 替代 emit

```python
from langgraph.config import get_stream_writer

async def planning_node(state: BossState) -> dict:
    writer = get_stream_writer()
    
    # 1. 通知前端：规划开始
    writer({"type": "task.planning", "data": {}})
    
    # 2. 构造 prompt
    persona_list = build_persona_list(available_personas)
    messages = build_planning_messages(
        state["user_intent"], 
        persona_list,
        state.get("previous_result")
    )
    
    # 3. 调用 LLM
    #    注意：即使这里用 ainvoke 而非 astream，
    #    stream_mode="messages" 也会自动捕获 token 流
    #    如果你想要更细粒度的控制，用 model.astream() + writer
    response = await model_router.ainvoke(messages, model="strong")
    
    # 4. 解析 plan
    plan = parse_task_plan(response.content)
    if plan is None:
        # 解析失败：用 interrupt 让用户知道并决定
        decision = interrupt({
            "type": "planning_failed",
            "raw_output": response.content[:2000],
            "message": "无法解析任务计划，是否用单任务模式继续？"
        })
        if decision["action"] == "retry":
            # 注意：interrupt resume 后节点从头执行
            # 所以这里会重新调用 LLM
            # 需要的话可以在 decision 中传入修改后的 intent
            return planning_node(state)  # 不对！节点会自动重跑
        elif decision["action"] == "fallback":
            plan = create_fallback_plan(state["user_intent"])
        else:
            return {"final_result": "任务已取消", "task_plan": None}
    
    # 5. 通知前端：计划就绪
    writer({"type": "task.plan_ready", "data": {
        "plan_id": plan.plan_id,
        "task_count": len(plan.tasks),
        "tasks": [t.model_dump() for t in plan.tasks]
    }})
    
    return {"task_plan": plan}
```

### 4.4 validate_node：interrupt 是一等公民

```python
async def validate_node(state: BossState) -> dict:
    plan = state["task_plan"]
    if plan is None:
        return {}  # planning 被取消了，直接跳过
    
    # 确定性校验（纯代码，无 LLM）
    errors = validator.validate(plan)
    
    if errors:
        # interrupt：暂停，等用户决定
        decision = interrupt({
            "type": "validation_error",
            "errors": [e.dict() for e in errors],
            "plan": plan.model_dump(),
            "message": "任务计划校验失败，请审查"
        })
        
        if decision["action"] == "fix":
            # 用户提供了修改后的 plan
            return {"task_plan": TaskPlan(**decision["fixed_plan"])}
        elif decision["action"] == "approve_anyway":
            pass  # 继续执行
        else:
            return {"final_result": "任务已取消", "task_plan": None}
    
    # 可选：复杂计划需要人工预览
    if should_require_preview(plan):
        decision = interrupt({
            "type": "plan_review",
            "plan": plan.model_dump(),
            "message": f"计划包含 {len(plan.tasks)} 个任务，请确认"
        })
        if decision["action"] != "approve":
            return {"final_result": "任务已取消", "task_plan": None}
    
    return {}  # 校验通过，state 不变
```

**注意 `interrupt()` 的语义**：
1. 它在节点**内部**暂停，不需要路由到 END
2. Resume 后，**节点从头执行**——所以 `validator.validate(plan)` 会再跑一次
3. 因为 `validate` 是纯函数、无副作用——重跑是安全的（幂等性！）

### 4.5 execute_node：并行执行 + interrupt 的正确处理

```python
import asyncio
from langgraph.config import get_stream_writer

async def execute_node(state: BossState) -> dict:
    writer = get_stream_writer()
    plan = state["task_plan"]
    completed = set(state["completed_task_ids"])
    
    # 获取当前可执行的任务（依赖已满足）
    ready_tasks = plan.get_ready_tasks(completed)
    
    if not ready_tasks:
        return {}  # 没有任务了，should_continue_executing 会路由到 aggregate
    
    # 并行执行同一层的任务
    new_outputs = {}
    new_completed = []
    
    async def run_single(task):
        writer({"type": "task.executing", "data": {
            "task_id": task.task_id, 
            "persona": task.assigned_persona
        }})
        
        # 构建上游上下文（信封模式）
        upstream_context = build_upstream_context(
            task, state["task_outputs"]
        )
        
        try:
            # 执行 persona agent
            result = await persona_agent.ainvoke(
                build_task_input(task, upstream_context),
                {"recursion_limit": 10}
            )
            
            output = TaskOutput(
                task_id=task.task_id,
                summary=extract_structured_summary(result),  # 结构化摘要，非截断
                full_result=result,
                confidence=1.0
            )
            
            writer({"type": "task.completed", "data": {
                "task_id": task.task_id,
                "summary": output.summary
            }})
            
            return task.task_id, output, None
            
        except Exception as e:
            output = TaskOutput(
                task_id=task.task_id,
                summary=f"执行失败: {str(e)}",
                full_result="",
                confidence=0.0
            )
            
            writer({"type": "task.failed", "data": {
                "task_id": task.task_id,
                "error": str(e)
            }})
            
            return task.task_id, output, e
    
    # 并行执行
    results = await asyncio.gather(
        *[run_single(t) for t in ready_tasks],
        return_exceptions=False  # 异常已在内部处理
    )
    
    # 收集结果
    failed_tasks = []
    for task_id, output, error in results:
        new_outputs[task_id] = output
        new_completed.append(task_id)
        if error:
            failed_tasks.append(task_id)
    
    # 如果有失败的任务，interrupt 让用户决定
    if failed_tasks:
        decision = interrupt({
            "type": "execution_error",
            "failed_tasks": failed_tasks,
            "message": f"{len(failed_tasks)} 个任务执行失败，是否继续？"
        })
        # 注意：interrupt resume 后节点从头执行
        # 所以 ready_tasks 会重新计算
        # 已完成的任务在 completed_task_ids 里，不会重复执行
        # ⚠️ 但 new_outputs 和 new_completed 还没写入 state！
        # 这就是 interrupt 前代码必须幂等的原因
    
    return {
        "task_outputs": new_outputs,        # reducer 会合并
        "completed_task_ids": new_completed  # reducer 会 append
    }
```

**这里有一个微妙的问题**：interrupt 后节点重跑，但 `asyncio.gather` 的结果还没写入 state。这意味着并行执行的 LLM 调用会**再次发生**。

**解决方案**——将每个 task 的执行结果在成功时立即通过 `get_stream_writer` 发出，并在 interrupt resume 时检查 `state["task_outputs"]` 中已有的结果来跳过：

```python
async def run_single(task, existing_outputs):
    # 幂等性：如果已经有结果，跳过
    if task.task_id in existing_outputs:
        return task.task_id, existing_outputs[task.task_id], None
    
    # ... 执行逻辑 ...
```

---

## 五、SSE 事件传播的正确架构

### 5.1 分离"实时流"和"持久化事件"

```
核心认知：不是所有 SSE 事件都需要持久化

┌─────────────────────────────────────────────┐
│             事件分类                          │
│                                               │
│  持久化事件 (写 events 表):                    │
│    - task.created                              │
│    - task.plan_ready                           │
│    - task.completed / task.failed              │
│    - interrupt (HiTL 请求)                     │
│    → 用于: 断线重连补发、历史回溯、审计         │
│                                               │
│  瞬态事件 (仅实时推送):                        │
│    - llm.token (每个 token)                    │
│    - task.heartbeat                            │
│    - task.progress (进度百分比)                 │
│    → 用于: 实时体验、不需要持久化              │
│    → 丢了就丢了（前端断线重连后拿到最终状态）   │
└─────────────────────────────────────────────┘
```

### 5.2 断线重连协议

```
SSE 规范本身就支持断线重连：

服务端发送:
  id: 42
  event: task.plan_ready
  data: {"plan_id": "p1", "task_count": 3}

客户端断线后自动重连，发送 header:
  Last-Event-ID: 42

服务端处理:
  1. 从 events 表查 seq > 42 的所有持久化事件
  2. 逐条发给客户端（补发）
  3. 补发完毕后，切换到实时流（graph.astream）

FastAPI 实现:
```

```python
@app.get("/api/v1/tasks/{thread_id}/stream")
async def stream_task(
    thread_id: str,
    request: Request,
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
):
    last_seq = int(last_event_id) if last_event_id else 0
    
    async def event_generator():
        # Phase 1: 补发历史持久化事件
        missed_events = await db.fetch_events_after(thread_id, last_seq)
        for event in missed_events:
            yield {
                "id": str(event.seq),
                "event": event.event_type,
                "data": json.dumps(event.data)
            }
        
        # Phase 2: 检查任务当前状态
        task = await db.get_task(thread_id)
        if task.status in ("completed", "failed", "cancelled"):
            return  # 任务已结束，不需要实时流
        
        # Phase 3: 实时流
        config = {"configurable": {"thread_id": thread_id}}
        
        if task.status == "interrupted":
            # 任务在等待 HiTL，不需要 stream graph
            # 但保持连接活跃以接收 resume 后的流
            while True:
                if await request.is_disconnected():
                    return
                # 检查任务状态是否变了
                task = await db.get_task(thread_id)
                if task.status != "interrupted":
                    break
                yield {"event": "keepalive", "data": ""}
                await asyncio.sleep(15)
        
        # Phase 4: stream graph execution
        async for chunk in graph.astream(
            None, config,
            stream_mode=["messages", "updates", "custom"],
            version="v2",
        ):
            if await request.is_disconnected():
                return
            
            if chunk["type"] == "messages":
                msg, meta = chunk["data"]
                if msg.content:
                    # 瞬态事件：不持久化，不带 id
                    yield {
                        "event": "llm.token",
                        "data": json.dumps({
                            "content": msg.content,
                            "node": meta.get("langgraph_node")
                        })
                    }
            
            elif chunk["type"] == "custom":
                event_data = chunk["data"]
                event_type = event_data.get("type", "custom")
                
                if should_persist(event_type):
                    # 持久化事件：写 DB，带 id
                    seq = await db.persist_event(thread_id, event_type, event_data)
                    yield {
                        "id": str(seq),
                        "event": event_type,
                        "data": json.dumps(event_data.get("data", {}))
                    }
                else:
                    yield {
                        "event": event_type,
                        "data": json.dumps(event_data.get("data", {}))
                    }
            
            elif chunk["type"] == "updates":
                for node_name, state_update in chunk["data"].items():
                    seq = await db.persist_event(
                        thread_id, "node.completed", {"node": node_name}
                    )
                    yield {
                        "id": str(seq),
                        "event": "node.completed",
                        "data": json.dumps({"node": node_name})
                    }
    
    return EventSourceResponse(event_generator())
```

### 5.3 关键洞察：SSE 连接和图执行可以解耦

```
你现在的模型:
  POST /tasks → 启动图执行 (create_task)
  GET /events/stream → 被动接收事件

问题: 图执行和 SSE 连接的生命周期绑定在一起

正确的模型有两种选择:

模型 A: SSE 连接驱动图执行
  POST /tasks → 只写 DB (status=pending)
  GET /tasks/{id}/stream →
    1. 补发历史事件
    2. 如果 status=pending → graph.ainvoke() 开始执行
       如果 status=running → 加入已有的执行流
       如果 status=interrupted → 等待 resume
    3. 图执行的输出直接通过 SSE 推给这个连接的客户端
    
  好处: 简单，不需要后台 worker
  缺点: 客户端断开 = 图执行可能中断（需要 checkpoint 恢复）

模型 B: Worker 驱动图执行 (适合生产)
  POST /tasks → 写 DB + pg_notify('new_task')
  Worker process:
    LISTEN new_task →
    graph.ainvoke() → 
    事件写入 events 表 + pg_notify('event:{thread_id}')
  
  GET /tasks/{id}/stream →
    1. 补发历史事件
    2. asyncpg LISTEN event:{thread_id} → 实时推送
    
  好处: 图执行不依赖客户端连接，进程隔离
  缺点: 需要 worker 进程管理（但 Docker Compose 天然支持）
```

---

## 六、HiTL 恢复的完整协议

```python
@app.post("/api/v1/tasks/{thread_id}/resume")
async def resume_task(
    thread_id: str,
    body: ResumeRequest,
    user: User = Depends(get_current_user)
):
    # 1. 幂等性检查
    task = await db.get_task(thread_id)
    if task.user_id != user.id:
        raise HTTPException(403)
    if task.status != "interrupted":
        raise HTTPException(409, f"Task is {task.status}, not interrupted")
    
    # 2. 乐观锁：确保只有一个 resume 成功
    updated = await db.update_task_status(
        thread_id, 
        expected_status="interrupted",  # CAS: compare-and-swap
        new_status="running"
    )
    if not updated:
        raise HTTPException(409, "Task already resumed by another request")
    
    # 3. 持久化 resume 事件
    await db.persist_event(thread_id, "hitl.resumed", {
        "action": body.action,
        "data": body.data
    })
    
    # 4. 返回成功 —— 实际执行由 SSE stream 触发
    #    客户端收到 200 后，会 re-subscribe SSE
    #    SSE endpoint 检测到 status=running，开始 graph.invoke(Command(resume=...))
    return {"status": "resumed"}
```

**关键设计决策**：
- `resume` API 只做状态转换（`interrupted → running`），不启动执行
- 执行由 SSE 连接的 `event_generator` 触发：检测到 `status=running` + 有 pending resume → `graph.invoke(Command(resume=...))`
- 乐观锁（CAS on status column）防止双击问题
- 完全不需要 `asyncio.create_task`

---

## 七、信封模式的正确实现

你原来的 `_truncate_summary(result, 1000 chars)` 是有损的。正确的做法：

```python
# 让 Persona Agent 自己生成结构化输出

TASK_EXECUTION_TEMPLATE = """
你需要完成以下任务:
{task_description}

{upstream_context}

请按以下格式输出:

## 执行摘要
(3-5 个要点，每个不超过 100 字)

## 详细结果
(完整的分析/调研/代码等)

## 关键数据
(结构化的关键发现，供下游任务使用)
"""

def build_task_output(raw_result: str) -> TaskOutput:
    """从 LLM 输出中提取结构化摘要"""
    # 解析 markdown 结构
    sections = parse_markdown_sections(raw_result)
    
    return TaskOutput(
        summary=sections.get("执行摘要", raw_result[:500]),  # fallback
        full_result=raw_result,
        key_data=sections.get("关键数据", ""),
        confidence=1.0
    )

def build_upstream_context(task, task_outputs):
    """信封模式：下游只看摘要 + 关键数据"""
    context_parts = []
    for dep_id in task.dependencies:
        dep_output = task_outputs.get(dep_id)
        if dep_output:
            context_parts.append(
                f"### 上游任务 [{dep_id}] 结果摘要:\n"
                f"{dep_output.summary}\n\n"
                f"### 关键数据:\n"
                f"{dep_output.key_data}"
            )
    
    if context_parts:
        return "## 上游任务上下文\n\n" + "\n\n---\n\n".join(context_parts)
    return ""
```

**改进点**：
1. **结构化输出**而非字符截断——让 LLM 自己决定什么是"摘要"
2. **关键数据**字段——下游任务可能需要具体的数据点（如"搜索到的 5 个框架名称"），不能在摘要中丢失
3. **Fallback**而非 silent degradation——如果 LLM 没按格式输出，用前 500 字兜底，但日志中标记

---

## 八、核心设计原则总结

```
┌─────────────────────────────────────────────────────────────────┐
│                   AgenticOS 工程不变式                            │
│                                                                   │
│  1. 状态在数据库，不在内存                                        │
│     → PostgreSQL 是唯一真相源                                     │
│     → 进程是无状态的、可随时重启的                                │
│                                                                   │
│  2. 用框架的原语，不要重新发明                                    │
│     → interrupt() 替代 current_phase + hitl_pending               │
│     → get_stream_writer() 替代 emit() 闭包                       │
│     → Checkpoint 替代 asyncio.create_task                         │
│     → Command(resume=) 替代 aupdate_state                        │
│                                                                   │
│  3. 所有 mutation 必须幂等                                        │
│     → interrupt 前的代码会重跑                                    │
│     → HiTL resume 通过 CAS 保证只执行一次                        │
│     → 已完成的 task 通过检查 completed_ids 跳过                   │
│                                                                   │
│  4. 事件分级：持久化 vs 瞬态                                     │
│     → 生命周期事件持久化（断线重连可补发）                        │
│     → LLM token 是瞬态的（丢了不影响正确性）                     │
│     → SSE id 只给持久化事件，实现 Last-Event-ID 重连             │
│                                                                   │
│  5. 信封模式用结构化摘要，不用字符截断                            │
│     → 让 Agent 自己提炼摘要（Agent 最了解自己的输出）             │
│     → 保留关键数据字段，防止信息有损传递                          │
│                                                                   │
│  6. 失败时告知用户，不要静默降级                                  │
│     → JSON 解析失败 → interrupt，不是 fallback                    │
│     → 任务执行失败 → interrupt，让用户决定重试/跳过               │
│     → 系统有权优雅降级，但必须让用户知道                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 九、实施路径——渐进式重构而非推翻重写

```
Phase 0: 理解
  └── 建立以上工程认知
  └── 跑通 LangGraph interrupt/resume 的最小 demo

Phase 1: 核心替换
  ├── State: 去掉 current_phase, hitl_pending
  ├── 节点: 用 interrupt() 替代手动 HiTL 逻辑
  ├── 图: 用条件边替代 route_next()
  ├── API: resume endpoint 用 Command(resume=)
  └── 验证: happy path + HiTL 中断恢复

Phase 2: 流式输出重建
  ├── 节点内用 get_stream_writer() 发自定义事件
  ├── SSE endpoint 消费 graph.astream() 的 v2 输出
  ├── 实现 Last-Event-ID 断线重连
  └── 前端适配新的 SSE 事件格式

Phase 3: 健壮性加固
  ├── tasks 表状态机 + CAS 乐观锁
  ├── SSE keepalive + 超时断开
  ├── resume 幂等性
  └── 进程重启 → checkpoint 恢复测试

Phase 4: 信封模式优化
  ├── 结构化摘要 prompt
  ├── key_data 字段
  └── 验证多任务 DAG 的信息传递完整性
```


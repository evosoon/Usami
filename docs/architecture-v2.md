# Usami v2 Architecture

> Worker-driven model with LangGraph framework primitives

## Design Principles

### Three Engineering Invariants

| # | Invariant | Implementation | Verification |
|---|-----------|----------------|--------------|
| I-1 | PostgreSQL is single source of truth | All state in DB, no in-memory `active_tasks` | `kill -9` Worker → restart recovers |
| I-2 | Reliable event delivery | Events persisted before notification | Disconnect → reconnect → replay from `last_seq` → no loss, no duplicates |
| I-3 | All mutations are idempotent | CAS (`UPDATE WHERE status='expected'`), dedup by seq | Same request twice = same result |

### Framework Primitives (v1 → v2)

| Capability | v1 (Manual) | v2 (Framework) |
|-----------|-------------|----------------|
| State machine | `current_phase` string | Graph topology IS the phase |
| HiTL | `hitl_pending` list + polling | `interrupt()` + `Command(resume=)` |
| Streaming | `emit()` closure passthrough | `get_stream_writer()` |
| Persistence | In-memory `active_tasks` | PostgreSQL + Checkpoint |

---

## System Architecture

```
┌─────────────────┐         ┌─────────────────┐
│   API Process   │         │  Worker Process │
│  (FastAPI)      │         │  (LangGraph)    │
│                 │         │                 │
│  POST /tasks ───┼──pg_notify──►  LISTEN     │
│                 │         │       │         │
│  GET /events ◄──┼─────────┼── astream()     │
│   (SSE)         │         │                 │
└────────┬────────┘         └────────┬────────┘
         │                           │
         │      PostgreSQL           │
         └──────────┬────────────────┘
                    │
            ┌───────┴───────┐
            │  events table │  ← Single source of truth
            │  tasks table  │
            │  checkpoints  │
            └───────────────┘
```

### Process Responsibilities

**API Process (FastAPI)**:
- Accept HTTP requests
- Write to database (`INSERT tasks`)
- Send pg_notify signals
- Serve SSE events (read from DB + listen for new)
- **Does NOT** execute LangGraph graphs

**Worker Process**:
- `LISTEN new_task, resume_task` channels
- CAS claim task (`UPDATE WHERE status='pending'`)
- Execute `graph.astream()` with `stream_mode=["messages", "updates", "custom"]`
- Dispatch chunks to dual channels
- Finalize task status
- Recover orphaned tasks on startup

---

## Graph Topology (5 Nodes)

```
START → plan → validate → execute → review → route_after_review
                            ↑                       │
                            └───────────────────────┘ (has ready tasks)
                                                    │
                                               aggregate → END
```

| Node | Responsibility | Interrupt? |
|------|---------------|------------|
| `plan` | Parse intent, generate TaskPlan | Yes (parse failure) |
| `validate` | DAG validation, optional preview | Yes (validation error, preview) |
| `execute` | Parallel task execution (`asyncio.gather`) | **No** (isolation) |
| `review` | Check failed tasks, trigger HiTL | Yes (failed tasks) |
| `aggregate` | Summarize results, generate report | No |

**Critical Design Decision**: `execute` node NEVER calls `interrupt()` — this avoids conflicts with `asyncio.gather()`. The `review` node is the **interrupt isolation layer**.

### Interrupt Cost Awareness

When `interrupt()` is called, the current node will be **re-executed** on resume. This has implications:

| Node | Re-execution Impact | Mitigation |
|------|---------------------|------------|
| `plan` | Re-invokes LLM | Acceptable (planning is fast) |
| `validate` | Re-runs validation | Pure function, no side effects |
| `review` | Re-checks results | Pure function, no side effects |
| `execute` | ⚠️ Would re-run all tasks | **Never interrupt in execute** |

---

## State Management

### BossState (TypedDict with Reducers)

```python
class BossState(TypedDict, total=False):
    user_intent: str
    thread_id: str
    task_plan: TaskPlan | None
    task_outputs: Annotated[dict, merge_task_outputs]   # merge reducer
    completed_task_ids: Annotated[list, operator.add]   # append-only reducer
    final_result: str | None
    previous_result: str | None  # for follow-up context
```

### Reducer Behavior

| Field | Reducer | Behavior |
|-------|---------|----------|
| `task_outputs` | `merge_task_outputs` | Dict merge (parallel-safe) |
| `completed_task_ids` | `operator.add` | Append-only list |

**Known Limitation**: `retry_failed` is NOT supported in MVP because `operator.add` is append-only. Failed task IDs cannot be removed from `completed_task_ids`. Design choice: degrade to `continue` instead of retry.

---

## Dual-Channel Event Dispatch

| Channel | Events | Characteristics |
|---------|--------|-----------------|
| **PostgreSQL + pg_notify** | `phase.change`, `interrupt`, `task.completed`, `task.failed`, `node.completed` | Has `seq`, replayable, persisted |
| **Redis pub/sub** | `llm.token` | No `seq`, transient, fire-and-forget |

### Event Classification

```python
PERSISTENT_EVENTS = {
    "phase.change",
    "task.completed_single",
    "task.failed_single",
    "interrupt",
    "task.completed",
    "task.failed",
    "task.created",
    "node.completed"
}

# In dispatch logic:
if is_persistent_event(event_type):
    await persist_and_notify(pool, thread_id, user_id, event_data)  # PostgreSQL
else:
    await redis.publish(f"stream:{user_id}", json.dumps(event_data))  # Redis
```

### pg_notify Payload Limit

PostgreSQL pg_notify has an **8KB payload limit**. Solution:
- Only pass references in payload: `{seq, thread_id, type}`
- Full event data stored in `events` table
- SSE endpoint reads full data from table

---

## SSE Timing Protocol

```
T0: LISTEN events:{user_id}          ← Listen first
T1: SELECT ... WHERE seq > last_seq  ← Then query history
T2: yield missed events              ← Replay
T3: Worker produces event N          ← Real-time via pg_notify
T4: queue.get() → dedup → yield      ← No loss, no duplicates
```

**Order matters**: "LISTEN first, query later" prevents race condition event loss.

### Deduplication

Events are deduplicated by `seq` number (per-user monotonic). The SSE endpoint maintains a `seen_seqs` set:

```python
if seq in seen_seqs:
    continue  # Skip duplicate
seen_seqs.add(seq)
yield event
```

---

## Database Schema (v2 Additions)

### tasks table

```sql
CREATE TABLE tasks (
    thread_id   VARCHAR(64) PRIMARY KEY,
    user_id     VARCHAR(64) NOT NULL,
    intent      TEXT NOT NULL,
    status      VARCHAR(20) DEFAULT 'pending'
                CHECK (status IN ('pending','running','interrupted','resuming','completed','failed')),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
```

### resume_requests table

```sql
CREATE TABLE resume_requests (
    id            SERIAL PRIMARY KEY,
    thread_id     VARCHAR(64) NOT NULL,
    resume_value  JSONB NOT NULL,
    consumed      BOOLEAN DEFAULT false,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
```

### Task Status State Machine

```
pending → running → completed
    │         │
    │         ├→ interrupted → resuming → running
    │         │
    │         └→ failed
    │
    └→ (claimed by another worker, CAS fails)
```

---

## API Endpoint Behavior (v2)

| Endpoint | v1 Behavior | v2 Behavior |
|----------|-------------|-------------|
| `POST /tasks` | `asyncio.create_task(graph.ainvoke())` | `INSERT tasks` + `pg_notify('new_task')` |
| `POST /tasks/{id}/resume` | `graph.aupdate_state()` + `ainvoke()` | CAS `interrupted→resuming` + `INSERT resume_requests` + `pg_notify('resume_task')` |
| `GET /tasks/{id}` | `graph.aget_state()` | Query `tasks` table + `events` table |

---

## Worker Implementation

### Main Loop

```python
async def worker_main():
    # 1. Recover orphaned tasks (status='running' from previous crash)
    await recover_orphaned_tasks()

    # 2. Listen for new tasks
    async for notification in pg_listen(['new_task', 'resume_task']):
        if notification.channel == 'new_task':
            asyncio.create_task(handle_new_task(notification.payload))
        elif notification.channel == 'resume_task':
            asyncio.create_task(handle_resume_task(notification.payload))
```

### Task Handling

```python
async def handle_new_task(thread_id: str):
    # CAS claim
    result = await db.execute(
        "UPDATE tasks SET status='running' WHERE thread_id=$1 AND status='pending'",
        thread_id
    )
    if result.rowcount == 0:
        return  # Already claimed by another worker

    # Read task details from DB (NOT from pg_notify payload)
    task = await db.fetchone("SELECT * FROM tasks WHERE thread_id=$1", thread_id)

    # Execute graph
    async for chunk in graph.astream({"user_intent": task.intent}, config):
        await dispatch_stream_chunk(chunk, thread_id, task.user_id)

    # Finalize
    await finalize_task(thread_id)
```

### Finalization

```python
async def finalize_task(thread_id: str):
    state = await graph.aget_state(config)

    if state.tasks:  # Has pending interrupts
        await db.execute(
            "UPDATE tasks SET status='interrupted' WHERE thread_id=$1",
            thread_id
        )
    else:
        await db.execute(
            "UPDATE tasks SET status='completed' WHERE thread_id=$1",
            thread_id
        )
```

---

## Common Pitfalls

| Pitfall | Consequence | Solution |
|---------|-------------|----------|
| Call `interrupt()` inside `asyncio.gather()` | Undefined behavior, potential deadlock | Use review node as isolation layer |
| Expect `retry_failed` to work | Task IDs stuck in `completed_task_ids` | Degrade to `continue`, document limitation |
| Put full event data in pg_notify | 8KB limit exceeded | Use references only, data in table |
| Query before LISTEN in SSE | Event loss race condition | "LISTEN first, query later" |
| Read intent from pg_notify payload | Payload too large, data inconsistency | Worker reads from `tasks` table |

---

## File Reference

| File | Purpose |
|------|---------|
| `backend/worker/main.py` | Worker process entry point |
| `backend/core/task_queue.py` | pg_notify helpers |
| `backend/core/state.py` | BossState TypedDict |
| `backend/agents/boss.py` | 5-node graph builder |
| `backend/agents/nodes.py` | Node implementations |
| `backend/api/routes.py` | HTTP API (DB writes only) |
| `backend/api/sse.py` | SSE endpoint (dual-channel) |
| `frontend/src/types/sse.ts` | Event type definitions |
| `frontend/src/stores/thread-store.ts` | Event processing logic |

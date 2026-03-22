# backend/

FastAPI + LangGraph multi-agent backend (v2 architecture).

## v2 Architecture Overview

The v2 refactor introduces a **Worker-driven model** where task execution is decoupled from the API process:

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

### Key Principles

| Principle | Implementation |
|-----------|---------------|
| **PostgreSQL is single source of truth** | All state in DB, `kill -9` Worker → restart recovers |
| **Reliable event delivery** | Disconnect → reconnect → replay from `last_seq` |
| **Idempotent mutations** | CAS (`UPDATE WHERE status='expected'`), dedup by seq |

### Framework Primitives (v2)

| Capability | v1 (Manual) | v2 (Framework) |
|-----------|-------------|----------------|
| State machine | `current_phase` string | Graph topology IS the phase |
| HiTL | `hitl_pending` list + polling | `interrupt()` + `Command(resume=)` |
| Streaming | `emit()` closure passthrough | `get_stream_writer()` |
| Persistence | In-memory `active_tasks` | PostgreSQL + Checkpoint |

## Directory structure

```
backend/
├── main.py                  # FastAPI entry + lifespan (v2: no task execution)
├── Dockerfile
├── pyproject.toml / uv.lock
├── pytest.ini / alembic.ini
├── worker/
│   ├── __init__.py
│   └── main.py              # Worker process: pg_notify consumer + graph executor
├── core/
│   ├── state.py             # BossState (TypedDict + Annotated reducers), Task, TaskPlan, TaskOutput
│   ├── task_queue.py        # pg_notify helpers (notify_new_task, persist_and_notify)
│   ├── config.py            # YAML + env loader -> AppConfig
│   ├── persona_factory.py   # YAML -> LangGraph ReAct agents
│   ├── tool_registry.py     # Multi-source tool loading (builtin + MCP + skill)
│   ├── model_router.py      # Task-type routing + CircuitBreaker + retry
│   ├── plan_validator.py    # Deterministic DAG validation of Boss output
│   ├── hitl.py              # HiTL evaluation logic (confidence/cost thresholds)
│   ├── memory.py            # SQLAlchemy models: Task, ResumeRequest, Event, User, etc.
│   ├── event_store.py       # Event retrieval (get_thread_events, list_user_threads)
│   ├── auth.py              # JWT auth, password hashing, FastAPI deps, CSRF check, token blacklist
│   └── push.py              # Web Push notifications via pywebpush (VAPID)
├── agents/
│   ├── boss.py              # Boss graph builder: 5-node topology (plan→validate→execute→review→aggregate)
│   ├── nodes.py             # Node functions with interrupt() and get_stream_writer()
│   └── prompts.py           # All prompt templates and message constants
├── api/
│   ├── routes.py            # REST endpoints (v2: DB writes + pg_notify, no graph execution)
│   ├── sse.py               # SSE endpoint (v2: dual-channel pg LISTEN + Redis subscribe)
│   ├── auth_routes.py       # Auth endpoints (login, refresh, logout)
│   ├── admin_routes.py      # Admin CRUD endpoints
│   └── notification_routes.py # Push subscription endpoints
├── scheduler/
│   ├── cron.py              # APScheduler cron jobs
│   └── events.py            # Redis pub/sub event bus
├── alembic/
│   └── versions/            # Migration scripts (006: tasks + resume_requests)
└── tests/
    ├── conftest.py          # Shared fixtures
    └── test_*.py            # Test modules
```

## v2 Graph Topology (5 Nodes)

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
| `execute` | Parallel task execution (asyncio.gather) | **No** (isolation) |
| `review` | Check failed tasks, trigger HiTL | Yes (failed tasks) |
| `aggregate` | Summarize results, generate report | No |

**Critical**: `execute` node NEVER calls `interrupt()` — this avoids conflicts with `asyncio.gather()`. The `review` node is the **interrupt isolation layer**.

## State Management (BossState)

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

**Reducer behavior**:
- `task_outputs`: Merges dicts (parallel-safe)
- `completed_task_ids`: Append-only (cannot remove items)

**Limitation**: `retry_failed` is not supported in MVP because `operator.add` is append-only. Failed task IDs cannot be removed from `completed_task_ids`.

## Dual-Channel Event Dispatch

| Channel | Events | Characteristics |
|---------|--------|-----------------|
| **PostgreSQL + pg_notify** | `phase.change`, `interrupt`, `task.completed`, `task.failed`, `node.completed` | Has `seq`, replayable, persisted |
| **Redis pub/sub** | `llm.token` | No `seq`, transient, fire-and-forget |

```python
# In worker/main.py
PERSISTENT_EVENTS = {"phase.change", "task.completed_single", "task.failed_single",
                     "interrupt", "task.completed", "task.failed", "task.created", "node.completed"}

if is_persistent_event(event_type):
    await persist_and_notify(pool, thread_id, user_id, event_data)  # PostgreSQL
else:
    await redis.publish(f"stream:{user_id}", json.dumps(event_data))  # Redis
```

**pg_notify payload limit**: Only pass references (`seq`, `thread_id`, `type`) — full event data in `events` table.

## SSE Timing Protocol

```
T0: LISTEN events:{user_id}          ← Listen first
T1: SELECT ... WHERE seq > last_seq  ← Then query history
T2: yield missed events              ← Replay
T3: Worker produces event N          ← Real-time via pg_notify
T4: queue.get() → dedup → yield      ← No loss, no duplicates
```

**Order matters**: "LISTEN first, query later" prevents race condition event loss.

## API Endpoints (v2)

| Endpoint | v1 Behavior | v2 Behavior |
|----------|-------------|-------------|
| `POST /tasks` | `asyncio.create_task(graph.ainvoke())` | `INSERT tasks` + `pg_notify('new_task')` |
| `POST /tasks/{id}/resume` | `graph.aupdate_state()` + `ainvoke()` | CAS `interrupted→resuming` + `INSERT resume_requests` + `pg_notify('resume_task')` |
| `GET /tasks/{id}` | `graph.aget_state()` | Query `tasks` table + `events` table |

## Worker Process

```bash
# Run worker
python -m worker.main
# Or via Docker
docker compose up worker
```

**Worker responsibilities**:
1. `LISTEN new_task, resume_task` channels
2. CAS claim task (`UPDATE WHERE status='pending'`)
3. `graph.astream()` with `stream_mode=["messages", "updates", "custom"]`
4. Dispatch chunks to dual channels
5. `finalize_task()`: check interrupt, update status
6. `recover_orphaned_tasks()`: resume on startup

## Module dependency graph

```
state.py          <- (no deps, TypedDict + Pydantic)
task_queue.py     <- (standalone, pg_notify helpers)
config.py         <- (reads YAML + env)
memory.py         <- state.py (SQLAlchemy: Task, ResumeRequest, Event)
model_router.py   <- (standalone)
tool_registry.py  <- (standalone)
plan_validator.py <- state.py
hitl.py           <- state.py
event_store.py    <- state.py, memory.py
auth.py           <- state.py, memory.py
push.py           <- config.py, memory.py
persona_factory.py <- tool_registry, model_router
prompts.py        <- (no deps, pure constants)
nodes.py          <- state, plan_validator, persona_factory, prompts
boss.py           <- nodes (graph builder)
routes.py         <- state, task_queue, event_store
sse.py            <- state, event_store, auth
worker/main.py    <- boss, task_queue, persona_factory
main.py           <- everything except worker
```

**Rule**: `core/` never imports from `agents/`, `api/`, `scheduler/`, or `worker/`.

## Key Constraints

### BossState uses TypedDict with Annotated reducers

```python
graph = StateGraph(BossState)  # Not StateGraph(dict)
```

Nodes return **partial dicts** — reducers merge into full state. No need for `{**state, ...updates}` pattern.

### User-facing strings are in Chinese

- `plan_validator.py` error messages
- `hitl.py` titles, descriptions, options
- `agents/prompts.py` `HITL_*` constants

### HiTL thresholds (in nodes.py review_node)

| Trigger | Condition |
|---------|-----------|
| Failed task | `confidence < 0.6` |

### main.py lifespan (v2)

```
config -> database -> auth -> push -> redis -> tool_registry -> persona_factory
-> hitl_gateway -> sse_manager -> checkpointer -> boss_graph -> scheduler
```

**Note**: API process builds `boss_graph` for health checks and scheduler, but does NOT execute tasks.

### Authentication

- **Tokens**: JWT in httpOnly cookies. Access token (15min JWT, 7d cookie), refresh token (7d).
- **CSRF**: Cookie-based auth requires `X-Usami-Request` header. Bearer auth (SSR) and SSE are exempt.
- **Token blacklist**: On logout, access token jti is added to Redis with TTL = remaining expiry. `get_current_user` checks blacklist (fail-open if Redis unavailable).
- **Dependencies**: `get_current_user` (API routes, with CSRF check), `get_current_user_sse` (SSE, no CSRF), `require_admin` (admin routes).

## Testing

```bash
# Run tests (from backend/)
uv run python -m pytest tests/ -v --tb=short

# With coverage
uv run python -m pytest tests/ -v --cov=core --cov=api --cov-report=term-missing
```

**v2 test changes**:
- `app_client` fixture mocks `get_session`, `persist_and_notify`, `notify_new_task`
- Task creation returns `status: "pending"` (not `"running"`)
- Some integration tests skipped (require real DB for CAS)

## Database (v2 additions)

New tables in `006_add_tasks_and_resume_requests.py`:

```sql
-- Task state (replaces in-memory active_tasks)
CREATE TABLE tasks (
    thread_id   VARCHAR(64) PRIMARY KEY,
    user_id     VARCHAR(64) NOT NULL,
    intent      TEXT NOT NULL,
    status      VARCHAR(20) DEFAULT 'pending',  -- pending/running/interrupted/resuming/completed/failed
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- HiTL resume requests (crash recovery)
CREATE TABLE resume_requests (
    id            SERIAL PRIMARY KEY,
    thread_id     VARCHAR(64) NOT NULL,
    resume_value  JSONB NOT NULL,
    consumed      BOOLEAN DEFAULT false,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
```

## Common Pitfalls (v2)

- **Don't** call `interrupt()` inside `asyncio.gather()` — use review node as isolation layer
- **Don't** expect `retry_failed` to work — `operator.add` reducer is append-only
- **Don't** put full event data in pg_notify payload — 8KB limit, use references only
- **Don't** query before LISTEN in SSE — causes event loss race condition
- **Don't** read `intent` from pg_notify payload — Worker reads from `tasks` table

## Prompt conventions

Same as before — all templates in `agents/prompts.py`, English for LLM instructions, Chinese for user-facing strings.

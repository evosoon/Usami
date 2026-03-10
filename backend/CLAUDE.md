# backend/

FastAPI + LangGraph multi-agent backend.

## Directory structure

```
backend/
├── main.py                  # FastAPI entry + lifespan (init chain)
├── Dockerfile
├── requirements.txt
├── pytest.ini / alembic.ini
├── core/
│   ├── state.py             # ALL Pydantic models (Task, TaskPlan, TaskOutput, HiTL*, AgentState)
│   ├── protocols.py         # Abstract interfaces (escape hatch from LangGraph)
│   ├── config.py            # YAML + env loader -> AppConfig
│   ├── persona_factory.py   # YAML -> LangGraph ReAct agents
│   ├── tool_registry.py     # Multi-source tool loading (builtin + MCP + skill)
│   ├── model_router.py      # Task-type routing + CircuitBreaker + retry
│   ├── plan_validator.py    # Deterministic DAG validation of Boss output
│   ├── hitl.py              # HiTL gateway (confidence/cost/retry triggers)
│   └── memory.py            # SQLAlchemy models + DB init (Alembic)
├── agents/
│   └── boss.py              # Boss supervisor graph (planning -> validate -> execute -> aggregate)
├── api/
│   ├── routes.py            # REST endpoints (POST /tasks, GET /tasks/{id}, POST /tasks/{id}/hitl)
│   └── websocket.py         # WS /ws/{client_id} + ConnectionManager
├── scheduler/
│   ├── cron.py              # APScheduler cron jobs
│   └── events.py            # Redis pub/sub event bus
├── alembic/
│   └── versions/            # Migration scripts
└── tests/
    ├── conftest.py          # Shared fixtures (validator, hitl_gateway, app_client)
    └── test_*.py            # 5 test modules, 70 cases
```

## Module dependency graph (import direction)

```
state.py          <- (no deps, pure Pydantic — foundation of everything)
protocols.py      <- state.py
config.py         <- (reads YAML + env, no core deps)
memory.py         <- state.py (SQLAlchemy models mirror Pydantic)
model_router.py   <- (standalone, uses langchain_openai)
tool_registry.py  <- (standalone, uses langchain_core.tools)
plan_validator.py <- state.py
hitl.py           <- state.py
persona_factory.py <- tool_registry, model_router
boss.py           <- state, plan_validator, hitl, persona_factory
routes.py         <- state (HiTLResponse only)
websocket.py      <- state (HiTLResponse only)
main.py           <- everything
```

**Rule**: `core/` never imports from `agents/`, `api/`, or `scheduler/`.

## Key constraints

### boss.py uses StateGraph(dict), NOT AgentState

```python
graph = StateGraph(dict)  # line 368
```

Checkpoint values are plain dicts. When reading state via `aget_state()`, fields like `task_plan` may be dict or Pydantic. Always handle both:

```python
plan_dict = task_plan.model_dump() if hasattr(task_plan, "model_dump") else task_plan
```

### Error messages are in Chinese

`plan_validator.py` returns Chinese strings. Tests must assert against these exact strings:
- `"任务计划为空"`
- `"存在重复的任务 ID"`
- `"不存在的 Persona"`
- `"依赖不存在的任务"`
- `"检测到循环依赖"`

### HiTL trigger thresholds (hardcoded in hitl.py)

| Trigger | Condition | Type |
|---|---|---|
| Low confidence | `< 0.6` | CLARIFICATION |
| Cost alert | `>= budget * 0.80` | APPROVAL |
| Retry exhaustion | `>= 2` | ERROR |

Evaluation order matters: confidence -> cost -> retry. First match wins.

### Confidence values are hardcoded in boss.py

- Success: `0.8` (won't trigger HiTL)
- Failure: `0.0` (always triggers)
- Final aggregation: `1.0`

### main.py lifespan initialization order

```
config -> database -> tool_registry -> persona_factory -> hitl_gateway
-> checkpointer (optional, may fail) -> boss_graph -> ws_manager -> scheduler
```

Checkpointer failure is non-fatal — system runs without persistence.

### API request/response models live in routes.py

`TaskRequest`, `TaskResponse`, `HiTLResolveRequest` are in `api/routes.py`, not `core/state.py`. This is intentional — API models are separate from domain models.

## Testing rules

- Fixtures in `conftest.py`: reuse `validator`, `hitl_gateway`, `simple_plan`, `task_output_*`, `app_client`.
- `app_client` fixture mocks `boss_graph`, `persona_factory`, `config`, `tool_registry`, `scheduler`. Imports `from main import app` — requires all transitive deps installed.
- `asyncio_mode = auto` in pytest.ini — no need for `@pytest.mark.asyncio` on test functions using async fixtures.
- For new core module tests: add fixture in conftest, create `tests/test_<module>.py`.
- For new API endpoint tests: add to `tests/test_routes.py`, use `app_client` fixture.

## Database migrations

- Models in `core/memory.py` (SQLAlchemy): `TaskLog`, `HiTLEventLog`, `RoutingLog`.
- `init_database()` runs `alembic upgrade head` (sync, blocks briefly at startup).
- `init_database_for_tests()` uses `create_all()` — fast, skips Alembic.
- New table: add SQLAlchemy model in `memory.py`, then `alembic revision --autogenerate`.
- Alembic env.py converts `postgresql://` to `postgresql+psycopg://` (sync driver).

## Common pitfalls

- **Don't** call `boss_graph.ainvoke()` without `config={"configurable": {"thread_id": ...}}` — checkpoint requires thread_id.
- **Don't** add tools to personas.yaml without implementing them in `tool_registry.py` `BUILTIN_TOOL_MAP` — it logs a warning but the tool won't work.
- **Don't** use `class Config:` in new Pydantic models — use `model_config = ConfigDict(...)` (V2 style). Existing `AgentState` uses deprecated V1 style.
- **Don't** import heavy modules (langgraph, langchain) at module top level in test files — use lazy imports or ensure deps are installed.
- **Don't** add `send_notification` tool calls — it's declared in tools.yaml but has no implementation in BUILTIN_TOOL_MAP.

# Usami

Personal AI Operating System — multi-agent orchestration for technical research and knowledge synthesis.

> Agent 不是在「帮人做事」，而是在成为你的知识工作搭档。

## What it does

用户输入一句自然语言意图，Usami 自动：

1. **Boss** 理解意图，分解为子任务 DAG
2. **PlanValidator** 确定性校验 DAG 合法性（循环、Persona 存在性、依赖引用）
3. **Specialist Personas**（Researcher / Writer / Analyst）按拓扑序执行
4. **HiTL Gateway** 在不确定时主动暂停，交由人类决策
5. **Boss** 汇总所有子任务结果，生成最终交付物

```
User: "帮我调研主流 Agent 框架的技术路线差异"
  ↓
Boss → TaskPlan DAG:
  T1: Researcher — 搜索各框架信息
  T2: Researcher — 对比分析 (← T1)
  T3: Analyst   — 提炼认知关联 (← T2)
  T4: Writer    — 输出报告 (← T2 + T3)
  ↓
PlanValidator ✓ → Execute → HiTL (if needed) → Aggregate → Deliver
```

## Architecture

```
┌─ Interaction ──────────────────────────────────────────────────────┐
│  Next.js 16 (React 19) + SSE (real-time events) + REST API        │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
┌─ Control Plane ──────────────▼─────────────────────────────────────┐
│  Boss Persona (LLM) → PlanValidator (deterministic) → HiTL Gate  │
│  LangGraph StateGraph: init→planning→validating→executing→done    │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ Task DAG
┌─ Execution Layer ────────────▼─────────────────────────────────────┐
│  Researcher (medium) │ Writer (strong) │ Analyst (strong)  │ ...  │
│  Config-driven Personas — YAML config, no code per agent          │
│  Envelope Pattern: summary ≤500 tok downstream, full_result on-demand │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
┌─ Infrastructure ─────────────▼─────────────────────────────────────┐
│  LiteLLM Proxy  │ PostgreSQL+pgvector │ Redis  │ SearXNG          │
│  (model routing    (checkpoint+logs      (SSE      (web search     │
│   +circuit breaker  +event sourcing)     pub/sub)   engine)        │
└────────────────────────────────────────────────────────────────────┘
```

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (App Router) + React 19 + Zustand + TanStack Query |
| UI | shadcn/ui (base-nova) + Tailwind CSS v4 + next-intl (zh/en) |
| API | FastAPI 0.115 + Uvicorn + SSE (Server-Sent Events) |
| Agent runtime | LangGraph 0.4 + LangChain 0.3 |
| LLM gateway | LiteLLM Proxy (strong=Claude Sonnet 4, medium/light=GPT-4o-mini) |
| Database | PostgreSQL 16 (pgvector) + SQLAlchemy 2 (async) + Alembic |
| Cache / Events | Redis 7 (SSE pub/sub + checkpoints) + APScheduler 3 |
| Search | SearXNG (self-hosted search engine) |
| Infra | Docker Compose (6 services: backend, frontend, postgres, redis, litellm, searxng) |
| Testing | pytest 8 + pytest-asyncio (129 test cases) |

## Quick start

```bash
# 1. Clone
git clone <repo-url>
cd usami

# 2. Configure
just init
# Edit .env — fill in OPENAI_API_KEY and/or ANTHROPIC_API_KEY

# 3. Launch
just up

# 4. Verify
just health
# → {"service": "Usami", "status": "ok", "litellm": "ok", "circuit_breaker": "closed"}
```

**Service endpoints:**

| Service | URL |
|---|---|
| Frontend (UI) | http://localhost:42000 |
| Backend API | http://localhost:42001 |
| API docs (Swagger) | http://localhost:42001/docs |
| LiteLLM Proxy | http://localhost:42002 |
| SearXNG | http://localhost:42080 |

Ports are configurable via `.env` (see `BACKEND_PORT`, `FRONTEND_PORT`, `LITELLM_PORT`, etc.) to avoid conflicts with other Docker projects on the same host.

## Project structure

```
usami/
├── CLAUDE.md                   # AI development guide (project-level)
├── docker-compose.yml          # 6 services: backend, frontend, postgres, redis, litellm, searxng
├── docker-compose.override.yml # Dev overrides: hot-reload (auto-merged by docker compose)
├── Justfile                    # Command runner (just up, just test, just lint, ...)
├── .env.example                # Environment variables template
│
├── config/                     # Declarative configuration (no code changes needed)
│   ├── CLAUDE.md               #   AI guide: YAML schema + cross-file consistency
│   ├── personas.yaml           #   Agent definitions (boss, researcher, writer, analyst)
│   ├── tools.yaml              #   Tool registry + permission levels + MCP servers
│   ├── routing.yaml            #   Model tier routing rules + budget limits
│   └── litellm_config.yaml     #   LLM provider mapping (strong/medium/light tiers)
│
├── frontend/                   # Next.js 16 frontend (React 19 + Zustand + TanStack Query)
│   ├── CLAUDE.md               #   AI guide: tech stack, architecture patterns, conventions
│   ├── src/
│   │   ├── app/                #   App Router pages (landing, login, chat, admin, share)
│   │   ├── components/         #   UI components (chat, task DAG, HiTL, admin panels)
│   │   ├── stores/             #   Zustand stores (auth, SSE, thread, notification)
│   │   ├── hooks/              #   TanStack Query hooks + derived state
│   │   ├── lib/                #   API clients, SSE client, constants
│   │   ├── types/              #   TypeScript types (mirrors backend Pydantic)
│   │   └── i18n/               #   next-intl config (zh/en)
│   └── messages/               #   i18n translation files (zh.json, en.json)
│
├── backend/                    # Python backend (FastAPI + LangGraph)
│   ├── CLAUDE.md               #   AI guide: module map, constraints, pitfalls
│   ├── main.py                 #   FastAPI entry + lifespan initialization chain
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── core/                   #   Core business logic (13 modules, each <400 lines)
│   │   ├── state.py            #     ALL domain models (Task, TaskPlan, TaskOutput, HiTL*)
│   │   ├── protocols.py        #     Runtime abstraction — LangGraph escape hatch
│   │   ├── config.py           #     YAML + env config loader
│   │   ├── persona_factory.py  #     YAML → LangGraph ReAct agents
│   │   ├── tool_registry.py    #     Multi-source tools (builtin + MCP + skill)
│   │   ├── model_router.py     #     Task-type routing + CircuitBreaker + retry
│   │   ├── plan_validator.py   #     Deterministic DAG validation
│   │   ├── hitl.py             #     HiTL gateway (confidence/cost/retry triggers)
│   │   ├── memory.py           #     SQLAlchemy models + Alembic migration
│   │   ├── event_store.py      #     Event persistence + retrieval (event sourcing)
│   │   ├── auth.py             #     JWT auth + password hashing + admin seed
│   │   ├── push.py             #     Web Push notifications (VAPID)
│   │   └── rate_limit.py       #     Rate limiting (slowapi)
│   ├── agents/
│   │   ├── boss.py             #   Boss supervisor graph builder (StateGraph assembly)
│   │   ├── nodes.py            #   Boss graph node functions (planning, validate, execute, aggregate)
│   │   └── prompts.py          #   All LLM prompt templates (centralized)
│   ├── api/
│   │   ├── routes.py           #   REST: tasks, threads, HiTL, cancel, personas, tools
│   │   ├── sse.py              #   SSE: real-time event streaming (per-user directed routing)
│   │   ├── auth_routes.py      #   Auth: login, refresh, logout (httpOnly cookies)
│   │   ├── admin_routes.py     #   Admin: user CRUD
│   │   └── notification_routes.py # Push subscription management
│   ├── scheduler/
│   │   ├── cron.py             #   Cron scheduling (APScheduler)
│   │   └── events.py           #   Redis pub/sub event bus
│   ├── alembic/                #   Database migrations (5 versions)
│   └── tests/                  #   10 test modules, 129 cases
│
└── docs/                       # Human documentation
    ├── architecture.md         #   System architecture diagrams + data flow
    └── design-decisions.md     #   Design decision records (D1-D9, mapped to pre-mortem F1-F9)
```

## API

### REST

```
POST   /api/v1/tasks                       Create task (async execution, returns thread_id)
GET    /api/v1/tasks/{thread_id}           Get task status from event store
POST   /api/v1/tasks/{thread_id}/hitl      Resolve HiTL request and resume execution
POST   /api/v1/tasks/{thread_id}/cancel    Cancel a running task
GET    /api/v1/threads                     List user's threads
GET    /api/v1/threads/{thread_id}/events  Replay all events for a thread
DELETE /api/v1/threads/{thread_id}         Delete thread and all events
GET    /api/v1/personas                    List available personas
GET    /api/v1/tools                       List registered tools
GET    /api/v1/scheduler/jobs              List scheduled jobs
GET    /health                             Health check (LiteLLM + circuit breaker + Redis + SSE)
```

### Auth

```
POST   /api/v1/auth/login                  Login (email/password → httpOnly cookies)
POST   /api/v1/auth/refresh                Refresh access token
POST   /api/v1/auth/logout                 Clear auth cookies
```

### Admin

```
GET    /api/v1/admin/users                 List all users
POST   /api/v1/admin/users                 Create user
PATCH  /api/v1/admin/users/{user_id}       Update user role/status
```

### SSE (Server-Sent Events)

```
GET /api/v1/events/stream                  Real-time event stream (per-user directed routing)

Server → Client events:
  task.created, task.planning, task.planning_chunk, task.plan_ready,
  task.executing, task.progress, task.aggregating, task.result_chunk,
  task.completed, task.failed, hitl.request
```

## Design decisions

Every architectural choice maps to a pre-mortem failure mode (F1-F9). Full records: [docs/design-decisions.md](./docs/design-decisions.md)

| # | Decision | Prevents |
|---|---|---|
| D1 | LangGraph + `protocols.py` thin abstraction | F1: Framework lock-in |
| D2 | Boss (LLM) + PlanValidator (deterministic code) | F2: Boss hallucination |
| D3 | Envelope pattern (summary ≤500 tok + full_result) | F3: Context pollution |
| D4 | Static routing + logging pipeline | F4: Routing decay |
| D5 | Config-driven personas (YAML, no code per agent) | F5: Complexity explosion |
| D6 | Multi-source tool registry (builtin + MCP + skill) | Extensibility |
| D7 | Full HiTL event logging | F8: Progressive Trust data |
| D8 | MVP anchored to "tech research + knowledge synthesis" | F7: OS metaphor trap |
| D9 | Exploration engine architecture reserved | Future autonomous mode |

## Development

### Run tests

```bash
just test                       # all tests
just test -k test_hitl          # filtered
just test-cov                   # with coverage
```

### Database migrations

```bash
just migrate                    # apply pending migrations
just migration "add table"      # create new migration
```

### Add a new persona

1. Add entry to `config/personas.yaml`
2. Ensure all tools in the `tools` list exist in `config/tools.yaml` AND have implementations in `core/tool_registry.py`
3. Restart — no code changes needed

### Add a new tool

1. Add entry to `config/tools.yaml` with permission level
2. Implement tool function in `core/tool_registry.py` `BUILTIN_TOOL_MAP`
3. Assign to personas in `config/personas.yaml`

## Documentation

| Document | Audience | Purpose |
|---|---|---|
| `CLAUDE.md` (root) | AI | Project-level architecture, code style, commands |
| `backend/CLAUDE.md` | AI | Module map, constraints, testing rules, pitfalls |
| `frontend/CLAUDE.md` | AI | Tech stack, architecture patterns, conventions |
| `config/CLAUDE.md` | AI | YAML schema, cross-file consistency, how-to guides |
| `docs/architecture.md` | Human | System architecture diagrams and data flow |
| `docs/design-decisions.md` | Human | Design decision records (D1-D9) with rationale |

## Roadmap

| Phase | Focus | Status |
|---|---|---|
| **MVP** | Core pipeline: Boss → Persona → HiTL → Delivery. Full frontend. Infrastructure hardened. | Done |
| **v0.2** | Knowledge Base (RAG via pgvector) + MCP tool integration | Next |
| **v0.3** | Skill system + Sandbox (L3 permission code execution) | Planned |
| **v0.4** | Progressive Trust (learn from HiTL logs) + intelligent model routing | Planned |
| **v1.0** | Exploration Engine ("Soul B") — long-running autonomous research loops | Future |

## License

MIT

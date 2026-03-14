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
│  REST API (FastAPI)  +  WebSocket (real-time events + HiTL)       │
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
│  LiteLLM Proxy  │ PostgreSQL+pgvector │ Redis │ APScheduler       │
│  (model routing    (checkpoint+logs      (WM+     (cron+           │
│   +circuit breaker  +vector future)      events)  webhooks)        │
└────────────────────────────────────────────────────────────────────┘
```

## Tech stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.115 + Uvicorn + WebSocket |
| Agent runtime | LangGraph 0.4 + LangChain 0.3 |
| LLM gateway | LiteLLM Proxy (strong=Claude Sonnet 4, medium/light=GPT-4o-mini) |
| Database | PostgreSQL 16 (pgvector) + SQLAlchemy 2 (async) + Alembic |
| Cache / Events | Redis 7 + APScheduler 3 |
| Infra | Docker Compose (5 services) |
| Testing | pytest 8 + pytest-asyncio (70 test cases) |

## Quick start

```bash
# 1. Clone
git clone <repo-url>
cd usami

# 2. Configure
cp .env.example .env
# Edit .env — fill in OPENAI_API_KEY and/or ANTHROPIC_API_KEY

# 3. Launch
docker compose up -d

# 4. Verify
curl http://localhost:8000/health
# → {"service": "Usami", "status": "ok", "litellm": "ok", "circuit_breaker": "closed"}
```

**Service endpoints:**

| Service | URL |
|---|---|
| Backend API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| LiteLLM Proxy | http://localhost:4000 |

Ports are configurable via `.env` (see `BACKEND_PORT`, `LITELLM_PORT`, etc.) to avoid conflicts with other Docker projects on the same host.

## Project structure

```
usami/
├── CLAUDE.md                   # AI development guide (project-level)
├── docker-compose.yml          # 5 services: backend, frontend, postgres, redis, litellm
├── .env.example                # Environment variables template
│
├── config/                     # Declarative configuration (no code changes needed)
│   ├── CLAUDE.md               #   AI guide: YAML schema + cross-file consistency
│   ├── personas.yaml           #   Agent definitions (boss, researcher, writer, analyst)
│   ├── tools.yaml              #   Tool registry + permission levels + MCP servers
│   ├── routing.yaml            #   Model tier routing rules + budget limits
│   └── litellm_config.yaml     #   LLM provider mapping (strong/medium/light tiers)
│
├── backend/                    # Python backend
│   ├── CLAUDE.md               #   AI guide: module map, constraints, pitfalls
│   ├── main.py                 #   FastAPI entry + lifespan initialization chain
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── core/                   #   Core business logic (9 modules, each <400 lines)
│   │   ├── state.py            #     ALL domain models (Task, TaskPlan, TaskOutput, HiTL*)
│   │   ├── protocols.py        #     Runtime abstraction — LangGraph escape hatch
│   │   ├── config.py           #     YAML + env config loader
│   │   ├── persona_factory.py  #     YAML → LangGraph ReAct agents
│   │   ├── tool_registry.py    #     Multi-source tools (builtin + MCP + skill)
│   │   ├── model_router.py     #     Task-type routing + CircuitBreaker + retry
│   │   ├── plan_validator.py   #     Deterministic DAG validation
│   │   ├── hitl.py             #     HiTL gateway (confidence/cost/retry triggers)
│   │   └── memory.py           #     SQLAlchemy models + Alembic migration
│   ├── agents/
│   │   └── boss.py             #   Boss supervisor graph (orchestrator)
│   ├── api/
│   │   ├── routes.py           #   REST: POST /tasks, GET /tasks/{id}, POST /tasks/{id}/hitl
│   │   └── websocket.py        #   WS: real-time events + HiTL interaction
│   ├── scheduler/
│   │   ├── cron.py             #   Cron scheduling (APScheduler)
│   │   └── events.py           #   Redis pub/sub event bus
│   ├── alembic/                #   Database migrations
│   └── tests/                  #   5 test modules, 70 cases
│
└── docs/                       # Human documentation
    ├── architecture.md         #   System architecture diagrams + data flow
    └── design-decisions.md     #   Design decision records (D1-D9, mapped to pre-mortem F1-F9)
```

## API

### REST

```
POST   /api/v1/tasks              Create task (async execution, returns thread_id)
GET    /api/v1/tasks/{thread_id}  Get task status, plan, result, pending HiTL
POST   /api/v1/tasks/{thread_id}/hitl  Resolve HiTL request and resume execution
GET    /api/v1/personas           List available personas
GET    /api/v1/tools              List registered tools
GET    /api/v1/scheduler/jobs     List scheduled jobs
GET    /health                    Health check (LiteLLM + circuit breaker state)
```

### WebSocket

```
WS /ws/{client_id}

Server → Client:  task.created, task.planning, task.executing, task.completed,
                  task.failed, hitl.request, hitl.resolved
Client → Server:  hitl.response {request_id, decision, feedback}
                  task.cancel {thread_id}
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
cd backend
python -m pytest tests/ -v
python -m pytest tests/ -v --cov=core --cov=api --cov-report=term-missing
```

### Database migrations

```bash
cd backend

# Apply migrations
alembic upgrade head

# Create new migration after changing models in memory.py
alembic revision --autogenerate -m "add_new_table"
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
| `config/CLAUDE.md` | AI | YAML schema, cross-file consistency, how-to guides |
| `docs/architecture.md` | Human | System architecture diagrams and data flow |
| `docs/design-decisions.md` | Human | Design decision records (D1-D9) with rationale |

## Roadmap

| Phase | Focus |
|---|---|
| **MVP** (current) | Core pipeline: Boss → Persona → HiTL → Delivery. Infrastructure hardened. |
| **v0.2** | Knowledge Base (RAG via pgvector) + MCP tool integration |
| **v0.3** | Skill system + Sandbox (L3 permission) + Frontend (React + WebSocket) |
| **v0.4** | Progressive Trust (learn from HiTL logs) + intelligent model routing |
| **v1.0** | Exploration Engine ("Soul B") — long-running autonomous research loops |

## License

MIT

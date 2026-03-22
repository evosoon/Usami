# Usami

Personal AI Operating System — multi-agent orchestration for technical research and knowledge synthesis.

## v2 Architecture Overview

v2 introduces a **Worker-driven model** where task execution is decoupled from the API process:

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

### Key Invariants

| # | Invariant | Verification |
|---|-----------|--------------|
| I-1 | PostgreSQL is single source of truth | `kill -9` Worker → restart recovers |
| I-2 | Reliable event delivery | Disconnect → reconnect → replay from `last_seq` |
| I-3 | All mutations are idempotent | Same request twice = same result |

### Framework Primitives (v1 → v2)

| Capability | v1 (Manual) | v2 (Framework) |
|-----------|-------------|----------------|
| State machine | `current_phase` string | Graph topology IS the phase |
| HiTL | `hitl_pending` list + polling | `interrupt()` + `Command(resume=)` |
| Streaming | `emit()` closure passthrough | `get_stream_writer()` |
| Persistence | In-memory `active_tasks` | PostgreSQL + Checkpoint |

## Architecture (3 patterns to internalize)

1. **Boss-Worker State Machine**: LangGraph StateGraph with 5-node topology: `plan → validate → execute → review → aggregate`. Boss decomposes intent, specialist Personas execute in parallel, Boss aggregates. State uses `TypedDict` with `Annotated` reducers.
2. **Config-Driven Personas**: Adding a persona = editing `config/personas.yaml`. No Python file per agent. `PersonaFactory` reads YAML, creates LangGraph ReAct agents at startup.
3. **Envelope Pattern (F3)**: Agents pass `TaskOutput.summary` (<=500 tokens) downstream. `full_result` is only read by Boss during aggregation. Never pass full_result between Personas.

## Collaboration Workflow

See `docs/collaboration-workflow.md` for the standard human-AI collaboration workflow.

Key phases: **Analyze → Align → Plan → Implement → Clean → Reflect → Document → Commit → Next**

Artifacts per phase:
- **Plan**: `~/.claude/plans/*.md` (ephemeral) + TodoWrite
- **Reflect**: Patterns/anti-patterns learned
- **Document**: Update CLAUDE.md + docs/ (persistent)

## Code style

- Language rules (follow strictly):
  - **English**: Python code, comments, variable/function names, log event names, LLM prompt templates, CLAUDE.md files, skill files, YAML config keys, commit messages
  - **Chinese**: Error messages shown to end users, UI text
  - When unsure, default to English
- **Prompt centralization**: All LLM prompt templates live in `backend/agents/prompts.py`. No inline prompt strings in agent code. See `backend/CLAUDE.md` "Prompt conventions" for details.
- Logging: `structlog` only. Every log call uses keyword args: `logger.info("event_name", key=value)`.
- Models: Pydantic BaseModel for all data schemas. Define in `core/state.py`.
- Async: All I/O is async. Use `async def` + `await`. No blocking calls in async context.
- Imports: `from __future__ import annotations` at top of every module.
- File size: Each module < 400 lines. Split if approaching.
- No over-engineering: Don't add features, abstractions, or error handling beyond what's requested.

## Commands

This project uses `just` as its command runner and `uv` for Python deps. Run `just --list` to see all commands.

**Do NOT use bare `python` or `python3`** — always use `uv run`.

```bash
# First-time setup
just init                       # create .env from template
# Edit .env — fill in your API keys

# Docker (full stack — dev mode with hot-reload by default)
just up                         # start all services (dev, hot-reload)
just up-prod                    # start all services (production build)
just down                       # stop all services
just rebuild                    # rebuild images + restart
just logs                       # tail all logs
just logs backend               # tail one service

# Backend
just test                       # run tests
just test -k test_hitl          # filtered
just test-cov                   # with coverage
just lint                       # check (ruff)
just lint-fix                   # auto-fix

# Database
just migrate                    # apply pending migrations
just migration "add table"      # create new migration

# Frontend
just dev-frontend               # local dev server
just test-frontend              # unit tests (Vitest)
just test-frontend-e2e          # E2E tests (Playwright, requires dev server)
just lint-frontend              # ESLint

# Utilities
just health                     # backend health check
just env-check                  # audit .env vs .env.example
```

## Project layout

```
config/          YAML configs (personas, tools, routing, litellm). See config/CLAUDE.md
frontend/        Next.js 16 frontend (React 19 + Zustand + TanStack Query). See frontend/CLAUDE.md
backend/         Python backend (FastAPI + LangGraph). See backend/CLAUDE.md
  core/          Core business logic (13 modules)
  agents/        Agent graphs (boss.py, nodes.py, prompts.py)
  api/           REST + SSE (Server-Sent Events)
  scheduler/     Cron + event bus
  alembic/       DB migrations
  tests/         pytest suite (9 modules, 99 cases)
docs/            Human documentation (architecture, design decisions)
docker-compose.yml           7 services: backend, worker, frontend, postgres, redis, litellm, searxng
docker-compose.override.yml  Dev overrides: frontend hot-reload (auto-merged by docker compose)
```

## Do NOT

- Add new files to `core/` without updating `backend/CLAUDE.md` module map.
- Put Pydantic models outside `core/state.py` (except API request/response in `api/routes.py`).
- Import from `agents/` or `api/` inside `core/` — dependency flows one way: core <- agents <- api.
- Use `print()` — use `structlog` logger.
- Commit `.env` files or API keys.

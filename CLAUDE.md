# Usami

Personal AI Operating System — multi-agent orchestration for technical research and knowledge synthesis.

## Architecture (3 patterns to internalize)

1. **Boss-Worker State Machine**: LangGraph StateGraph(dict) drives `init -> planning -> validating -> executing -> aggregating -> done`. Boss decomposes intent, specialist Personas execute, Boss aggregates. All state is plain dict, not Pydantic.
2. **Config-Driven Personas**: Adding a persona = editing `config/personas.yaml`. No Python file per agent. `PersonaFactory` reads YAML, creates LangGraph ReAct agents at startup.
3. **Envelope Pattern (F3)**: Agents pass `TaskOutput.summary` (<=500 tokens) downstream. `full_result` is only read by Boss during aggregation. Never pass full_result between Personas.

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
  tests/         pytest suite (10 modules, 129 cases)
docs/            Human documentation (architecture, design decisions)
docker-compose.yml           6 services: backend, frontend, postgres, redis, litellm, searxng
docker-compose.override.yml  Dev overrides: frontend hot-reload (auto-merged by docker compose)
```

## Do NOT

- Add new files to `core/` without updating `backend/CLAUDE.md` module map.
- Put Pydantic models outside `core/state.py` (except API request/response in `api/routes.py`).
- Import from `agents/` or `api/` inside `core/` — dependency flows one way: core <- agents <- api.
- Use `print()` — use `structlog` logger.
- Commit `.env` files or API keys.

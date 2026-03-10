# Usami

Personal AI Operating System — multi-agent orchestration for technical research and knowledge synthesis.

## Architecture (3 patterns to internalize)

1. **Boss-Worker State Machine**: LangGraph StateGraph(dict) drives `init -> planning -> validating -> executing -> aggregating -> done`. Boss decomposes intent, specialist Personas execute, Boss aggregates. All state is plain dict, not Pydantic.
2. **Config-Driven Personas**: Adding a persona = editing `config/personas.yaml`. No Python file per agent. `PersonaFactory` reads YAML, creates LangGraph ReAct agents at startup.
3. **Envelope Pattern (F3)**: Agents pass `TaskOutput.summary` (<=500 tokens) downstream. `full_result` is only read by Boss during aggregation. Never pass full_result between Personas.

## Code style

- Language: Python code and comments in English. User-facing strings (prompts, error messages) in Chinese.
- Logging: `structlog` only. Every log call uses keyword args: `logger.info("event_name", key=value)`.
- Models: Pydantic BaseModel for all data schemas. Define in `core/state.py`.
- Async: All I/O is async. Use `async def` + `await`. No blocking calls in async context.
- Imports: `from __future__ import annotations` at top of every module.
- File size: Each module < 400 lines. Split if approaching.
- No over-engineering: Don't add features, abstractions, or error handling beyond what's requested.

## Commands

```bash
# Start all services (Docker)
docker compose up -d

# Run backend locally (from backend/)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Tests
python -m pytest tests/ -v
python -m pytest tests/ -v --cov=core --cov=api --cov-report=term-missing

# Database migration
alembic upgrade head                          # apply
alembic revision --autogenerate -m "msg"      # create new

# Health check
curl http://localhost:8000/health
```

## Project layout

```
config/          YAML configs (personas, tools, routing, litellm). See config/CLAUDE.md
backend/         Python backend (FastAPI + LangGraph). See backend/CLAUDE.md
  core/          Core business logic (9 modules)
  agents/        Agent graphs (boss.py)
  api/           REST + WebSocket
  scheduler/     Cron + event bus
  alembic/       DB migrations
  tests/         pytest suite
docs/            Human documentation (architecture, design decisions)
docker-compose.yml   5 services: backend, frontend, postgres, redis, litellm
```

## Do NOT

- Add new files to `core/` without updating `backend/CLAUDE.md` module map.
- Put Pydantic models outside `core/state.py` (except API request/response in `api/routes.py`).
- Import from `agents/` or `api/` inside `core/` — dependency flows one way: core <- agents <- api.
- Use `print()` — use `structlog` logger.
- Commit `.env` files or API keys.

# Usami — unified command runner
# Usage: just --list

# Default: show available commands
default:
    @just --list

# --- Setup ---

# Initialize .env with API key placeholders (safe: never overwrites)
init:
    @if [ ! -f .env ]; then \
        printf '# Usami — user overrides (only add what differs from .env.example)\n\n# --- LLM API Keys (fill in at least one) ---\nOPENAI_API_KEY=\nANTHROPIC_API_KEY=\n' > .env; \
        echo "Created .env — fill in your API keys, then run: just up"; \
    else \
        echo ".env already exists, skipping"; \
    fi

# Show env vars in .env.example but missing from .env
env-check:
    @echo "Checking .env against .env.example..."
    @diff <(grep -v '^#' .env.example | grep -v '^$$' | cut -d= -f1 | sort) \
          <(grep -v '^#' .env | grep -v '^$$' | cut -d= -f1 | sort) \
          --color=always || true

[private]
_ensure-env:
    @if [ ! -f .env ]; then \
        echo "ERROR: .env not found. Run 'just init' first."; \
        exit 1; \
    fi

# --- Docker (full stack) ---

# Start all services (dev mode with hot-reload by default)
up: _ensure-env
    docker compose up -d

# Start all services in production mode (skip override)
up-prod: _ensure-env
    docker compose -f docker-compose.yml up -d

# Stop all services
down:
    docker compose down

# Rebuild and start (after Dockerfile or dependency changes)
rebuild: _ensure-env
    docker compose up -d --build

# Tail logs (usage: just logs / just logs backend)
logs *service:
    docker compose logs -f {{ service }}

# --- Backend ---

# Run backend locally with hot-reload
dev-backend: _ensure-env
    cd backend && uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Run backend tests (usage: just test / just test -k test_hitl)
test *args: _ensure-env
    cd backend && uv run python -m pytest tests/ -v --tb=short {{ args }}

# Run backend tests with coverage
test-cov: _ensure-env
    cd backend && uv run python -m pytest tests/ -v --cov=core --cov=api --cov-report=term-missing

# Lint backend
lint:
    cd backend && uv run ruff check . && uv run ruff format --check .

# Auto-fix lint issues
lint-fix:
    cd backend && uv run ruff check --fix . && uv run ruff format .

# --- Frontend ---

# Run frontend dev server
dev-frontend:
    cd frontend && pnpm dev

# Build frontend
build-frontend:
    cd frontend && pnpm build

# Lint frontend
lint-frontend:
    cd frontend && pnpm lint

# --- Database ---

# Apply all pending migrations
migrate: _ensure-env
    cd backend && uv run alembic upgrade head

# Create new migration (usage: just migration "add user table")
migration msg: _ensure-env
    cd backend && uv run alembic revision --autogenerate -m "{{ msg }}"

# --- Utilities ---

# Health check
health:
    @curl -sf http://localhost:8000/health | python3 -m json.tool || echo "Backend not reachable"

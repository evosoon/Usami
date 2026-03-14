FROM python:3.12.2-slim

WORKDIR /app

# Create non-root user with home directory for uv cache
RUN groupadd -r appuser && useradd -r -g appuser -m appuser

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency files first (cache-friendly layer)
COPY pyproject.toml uv.lock .python-version ./

# Install dependencies (frozen = use exact lockfile versions)
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

# Change ownership to non-root user
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()" || exit 1

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

# Build from repository root: docker build -f apps/api/Dockerfile .
# Reuses the reviewed Python base already selected for isolated workers.
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
FROM ${PYTHON_IMAGE} AS build
WORKDIR /app
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1
RUN python -m pip install --no-cache-dir uv==0.12.10
COPY pyproject.toml uv.lock README.md ./
COPY third_party/scrapling ./third_party/scrapling
COPY third_party/agent-reach ./third_party/agent-reach
COPY third_party/scrapegraph-ai ./third_party/scrapegraph-ai
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM ${PYTHON_IMAGE} AS runtime
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    SCRAPEGRAPHAI_TELEMETRY_ENABLED=false HOME=/app \
    TIKTOKEN_CACHE_DIR=/app/.runtime/tiktoken-cache
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --home-dir /app app \
    && mkdir -p /app/.runtime /app/.cache && chown -R app:app /app
COPY --from=build --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app alembic.ini ./alembic.ini
COPY --chown=app:app scripts ./scripts
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).close()"]
CMD ["python", "-m", "uvicorn", "skriller.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

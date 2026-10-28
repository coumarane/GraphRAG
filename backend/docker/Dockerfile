# syntax=docker/dockerfile:1.7

FROM python:3.13-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --create-home --home-dir /app app

# The runtime uses the venv. The base image's pip still vendors setuptools
# 70.3.0, urllib3 2.7.0, msgpack 1.1.2, and an older certifi, including inside
# the ensurepip wheel. No current pip release vendors the patched copies.
RUN python -m pip uninstall -y pip \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip \
              /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
              /usr/local/lib/python3.13/ensurepip/_bundled \
    && rm -f /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13

COPY --from=ghcr.io/astral-sh/uv:0.7.12 /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies from the lockfile first so application-code edits
# don't invalidate this layer and force a full reinstall every build.
# openai/langchain/azure are already covered by uv.lock (llm extra + core
# deps), so no separate unlocked `uv pip install` is needed.
COPY pyproject.toml README.md uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project \
      --extra api --extra cli --extra postgres \
      --extra redis --extra minio --extra qdrant --extra neo4j \
      --extra llm \
      --extra observability --extra mcp

COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY config ./config

# Install the local project itself now that src/ is present. All
# dependencies are already installed above, so this is fast even without
# a cache hit.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra api --extra cli --extra postgres \
      --extra redis --extra minio --extra qdrant --extra neo4j \
      --extra llm \
      --extra observability --extra mcp

USER app


FROM base AS api

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=10 \
  CMD curl -fsS http://127.0.0.1:8000/api/v1/health/live || exit 1

CMD ["uvicorn", "graph_rag.api.app:get_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]


FROM base AS worker

CMD ["graph-rag", "worker", "--poll-interval", "1.0"]

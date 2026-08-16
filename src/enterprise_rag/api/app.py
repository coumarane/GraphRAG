"""FastAPI application factory."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from enterprise_rag.api.errors import register_exception_handlers
from enterprise_rag.api.routes import (
    assets,
    auth,
    documents,
    health,
    ingestion,
    ops,
    parsing_audit,
    retrieval,
    users,
)
from enterprise_rag.application.runtime.container import ServiceContainer
from enterprise_rag.application.runtime.runtime import build_runtime_container
from enterprise_rag.config.settings import get_settings
from enterprise_rag.infrastructure.observability import (
    ObservabilityMiddleware,
    configure_tracing,
    get_metrics,
)
from enterprise_rag.shared.logging import configure_logging, get_logger

logger = get_logger(__name__)


def _cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS")
    if raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    try:
        return list(get_settings().app.cors_origins)
    except Exception:
        return ["http://localhost:3000", "http://127.0.0.1:3000"]


def create_app(container: ServiceContainer | None = None) -> FastAPI:
    """Create the HTTP API with an injectable service container."""
    configure_logging()
    configure_tracing()
    resolved_container = container or build_runtime_container()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        svc: ServiceContainer = app.state.container
        if svc.auth_service is not None:
            try:
                created = await svc.auth_service.bootstrap_from_env()
                if created:
                    await svc.commit_db()
            except Exception as exc:  # noqa: BLE001
                logger.error("auth_bootstrap_failed", error=str(exc))
                raise
        yield

    app = FastAPI(
        title="Enterprise RAG-Anything",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    app.state.container = resolved_container
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(ObservabilityMiddleware)
    register_exception_handlers(app)

    api = APIRouter(prefix="/api/v1")
    api.include_router(health.router)
    api.include_router(auth.router)
    api.include_router(ops.router)
    api.include_router(documents.router)
    api.include_router(parsing_audit.router)
    api.include_router(ingestion.router)
    api.include_router(retrieval.router)
    api.include_router(assets.router)
    api.include_router(users.router)
    api.include_router(users.admin_router)
    app.include_router(api)

    @app.get("/metrics")
    async def prometheus_metrics() -> Response:
        body = get_metrics().render_prometheus()
        return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")

    return app


def get_app() -> FastAPI:
    """Uvicorn entrypoint target."""
    return create_app(build_runtime_container())

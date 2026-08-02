"""FastAPI application factory."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Response

from enterprise_rag.api.errors import register_exception_handlers
from enterprise_rag.api.routes import assets, documents, health, ingestion, retrieval
from enterprise_rag.application.runtime.container import ServiceContainer
from enterprise_rag.application.runtime.local import build_local_container
from enterprise_rag.infrastructure.observability import (
    ObservabilityMiddleware,
    configure_tracing,
    get_metrics,
)
from enterprise_rag.shared.logging import configure_logging


def create_app(container: ServiceContainer | None = None) -> FastAPI:
    """Create the HTTP API with an injectable service container."""
    configure_logging()
    configure_tracing()
    app = FastAPI(
        title="Enterprise RAG-Anything",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.container = container or build_local_container()
    app.add_middleware(ObservabilityMiddleware)
    register_exception_handlers(app)

    api = APIRouter(prefix="/api/v1")
    api.include_router(health.router)
    api.include_router(documents.router)
    api.include_router(ingestion.router)
    api.include_router(retrieval.router)
    api.include_router(assets.router)
    app.include_router(api)

    @app.get("/metrics")
    async def prometheus_metrics() -> Response:
        body = get_metrics().render_prometheus()
        return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")

    return app


def get_app() -> FastAPI:
    """Uvicorn entrypoint target."""
    return create_app()

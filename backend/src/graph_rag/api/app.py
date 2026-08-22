"""FastAPI application factory."""

from __future__ import annotations

import os
from contextlib import AsyncExitStack, asynccontextmanager, suppress

from fastapi import APIRouter, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from graph_rag.api.errors import register_exception_handlers
from graph_rag.api.routes import (
    assets,
    auth,
    conversations,
    documents,
    health,
    ingestion,
    ops,
    parsing_audit,
    retrieval,
    users,
)
from graph_rag.application.runtime.container import ServiceContainer
from graph_rag.application.runtime.runtime import build_runtime_container
from graph_rag.config.settings import get_settings
from graph_rag.infrastructure.observability import (
    ObservabilityMiddleware,
    configure_tracing,
    get_metrics,
)
from graph_rag.shared.logging import configure_logging, get_logger

logger = get_logger(__name__)


def _cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS")
    if raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    try:
        return list(get_settings().app.cors_origins)
    except Exception:
        return ["http://localhost:3000", "http://127.0.0.1:3000"]


def _mcp_enabled() -> bool:
    return os.environ.get("MCP_ENABLED", "false").strip().lower() not in {"0", "false", "no"}


def create_app(container: ServiceContainer | None = None) -> FastAPI:
    """Create the HTTP API with an injectable service container."""
    configure_logging()
    configure_tracing()
    resolved_container = container or build_runtime_container()
    mcp_enabled = _mcp_enabled()
    mcp_lifespan_cm = None
    if mcp_enabled:
        from graph_rag.mcp.transport import build_mcp_asgi_app

        mcp_asgi_app, mcp_lifespan_cm = build_mcp_asgi_app(resolved_container)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        import asyncio

        async with AsyncExitStack() as stack:
            if mcp_lifespan_cm is not None:
                await stack.enter_async_context(mcp_lifespan_cm())

            svc: ServiceContainer = app.state.container
            if svc.auth_service is not None:
                try:
                    created = await svc.auth_service.bootstrap_from_env()
                    if created:
                        await svc.commit_db()
                except Exception as exc:
                    logger.error("auth_bootstrap_failed", error=str(exc))
                    raise
            publisher_task = None
            if svc.outbox_publisher is not None and not svc.auto_process_ingest:
                stop = asyncio.Event()

                async def _publish_loop() -> None:
                    from graph_rag.config.settings import get_settings

                    interval = get_settings().worker.outbox_poll_seconds
                    while not stop.is_set():
                        try:
                            await svc.outbox_publisher.publish_once()
                        except Exception:
                            logger.exception("outbox_publisher_tick_failed")
                        try:
                            await asyncio.wait_for(stop.wait(), timeout=interval)
                        except TimeoutError:
                            continue

                publisher_task = asyncio.create_task(_publish_loop())
            try:
                yield
            finally:
                if publisher_task is not None:
                    stop.set()
                    publisher_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await publisher_task

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
    api.include_router(conversations.router)
    api.include_router(conversations.projects_router)
    api.include_router(assets.router)
    api.include_router(users.router)
    api.include_router(users.admin_router)
    app.include_router(api)

    if mcp_enabled:
        # Raw ASGI mount, not include_router: the MCP transport owns its own
        # wire protocol (session IDs, SSE framing) and JSON-RPC error shape.
        # CORS/ObservabilityMiddleware still wrap it (middleware wraps the
        # whole ASGI stack); FastAPI's typed exception handlers don't apply
        # here, which is fine since MCP errors aren't RFC 9457 problem details.
        app.mount("/api/v1/mcp", mcp_asgi_app)

    @app.get("/metrics")
    async def prometheus_metrics() -> Response:
        body = get_metrics().render_prometheus()
        return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")

    return app


def get_app() -> FastAPI:
    """Uvicorn entrypoint target."""
    return create_app(build_runtime_container())

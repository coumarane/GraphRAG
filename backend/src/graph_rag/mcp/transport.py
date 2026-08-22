"""ASGI wiring for the MCP Streamable HTTP transport.

``StreamableHTTPSessionManager.handle_request`` is a raw ASGI callable, not a
FastAPI route function -- it owns the wire protocol (session IDs, SSE
framing) itself. It's mounted via ``app.mount(...)``, not
``include_router(...)``; Starlette/FastAPI middleware (CORS,
``ObservabilityMiddleware``) still wraps mounted sub-apps, since middleware
wraps the whole ASGI stack, but this app's ``@app.exception_handler(...)``
registrations don't apply here -- MCP has its own JSON-RPC error shape, which
is the appropriate error format for this transport anyway.

Tenant resolution happens here, once per connection, before any MCP protocol
message is processed -- see ``mcp/auth.py`` for why it must not happen inside
a tool-call handler.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from graph_rag.application.runtime.container import ServiceContainer
from graph_rag.mcp import auth
from graph_rag.mcp.server import build_mcp_server
from graph_rag.shared.exceptions import GraphRagError

AsgiApp = Callable[[Scope, Receive, Send], Awaitable[None]]
LifespanFactory = Callable[[], AbstractAsyncContextManager[None]]


def build_mcp_asgi_app(container: ServiceContainer) -> tuple[AsgiApp, LifespanFactory]:
    """Return (asgi_app, lifespan_cm) for mounting at e.g. ``/api/v1/mcp``.

    ``lifespan_cm`` must be entered once, for the life of the process, from
    the host app's own lifespan -- it owns the session manager's task group.
    """
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    server = build_mcp_server(container)
    session_manager = StreamableHTTPSessionManager(app=server, stateless=True)

    async def asgi_app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await session_manager.handle_request(scope, receive, send)
            return
        try:
            tenant = await auth.resolve_tenant_from_scope(container, scope)
        except GraphRagError as exc:
            response = JSONResponse({"error": exc.to_dict()}, status_code=exc.http_status)
            await response(scope, receive, send)
            return
        token = auth.bind_tenant(tenant)
        try:
            await session_manager.handle_request(scope, receive, send)
        finally:
            auth.reset_tenant(token)

    @asynccontextmanager
    async def lifespan_cm() -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    return asgi_app, lifespan_cm

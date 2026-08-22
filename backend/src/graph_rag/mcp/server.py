"""Builds the low-level MCP ``Server``: tool listing + dispatch.

Uses ``mcp.server.lowlevel.Server`` rather than the ``FastMCP`` convenience
wrapper -- ``FastMCP`` hands back a complete, separate Starlette app meant to
be ``.mount()``-ed with its own error handling; the low-level ``Server`` lets
the transport (``transport.py``) integrate directly with this app's ASGI
stack instead.
"""

from __future__ import annotations

from typing import Any

from mcp import types
from mcp.server.lowlevel import Server

from graph_rag.application.runtime.container import ServiceContainer
from graph_rag.mcp import auth
from graph_rag.mcp.tools import TOOLS, TOOLS_BY_NAME
from graph_rag.shared.exceptions import GraphRagError
from graph_rag.shared.logging import get_logger

logger = get_logger(__name__)


def build_mcp_server(container: ServiceContainer) -> Server[Any, Any]:
    """One ``Server`` instance per process, closing over the shared container."""
    server: Server[Any, Any] = Server(name="graph-rag", version="0.1.0")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(name=tool.name, description=tool.description, inputSchema=tool.input_schema)
            for tool in TOOLS
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        spec = TOOLS_BY_NAME.get(name)
        if spec is None:
            raise ValueError(f"Unknown tool: {name}")
        tenant = auth.current_tenant()
        try:
            return await spec.handler(container, tenant, arguments)
        except GraphRagError as exc:
            # .message is already the safe, user-facing text used for the
            # REST API's problem-details body (api/errors.py) -- reuse it.
            logger.warning("mcp_tool_call_failed", tool=name, code=exc.code, error=exc.message)
            raise RuntimeError(f"{exc.code}: {exc.message}") from None
        except Exception:
            # The SDK's own call_tool() wrapper does `str(exc)` verbatim into
            # the client-visible error result -- never let an arbitrary
            # exception's message (SQL text, stack internals, ...) reach an
            # external MCP caller. Full detail goes to the server log only.
            logger.exception("mcp_tool_call_unhandled_error", tool=name)
            raise RuntimeError("Internal error processing tool call") from None

    return server

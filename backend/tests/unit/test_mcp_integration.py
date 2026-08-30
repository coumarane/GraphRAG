"""End-to-end MCP client against the mounted transport.

Uses the real ``mcp`` client SDK's streamable-HTTP transport, bound to the
FastAPI app via an in-process ASGI transport (no real socket/port needed) --
exercises the actual wire protocol, not just the Python-level handler
functions.
"""

from __future__ import annotations

import os
from uuid import uuid4

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from graph_rag.api.app import create_app
from graph_rag.application.runtime.local import build_local_container
from graph_rag.config.settings import clear_settings_cache


def _client_factory(app, default_headers):
    def factory(headers=None, timeout=None, auth=None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://mcp-test",
            headers={**default_headers, **(headers or {})},
            timeout=timeout or 10.0,
            auth=auth,
        )

    return factory


async def test_mcp_client_lists_and_calls_tools(monkeypatch) -> None:
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("API_SERVICE_KEY", "integration-test-key")
    clear_settings_cache()
    try:
        container = build_local_container()
        app = create_app(container)
        tenant_id = uuid4()

        headers = {
            "X-Api-Service-Key": "integration-test-key",
            "X-Tenant-ID": str(tenant_id),
            "X-Principal": "mcp-integration-test",
        }

        async with (
            app.router.lifespan_context(app),
            streamablehttp_client(
                "http://mcp-test/api/v1/mcp/",
                headers=headers,
                httpx_client_factory=_client_factory(app, headers),
            ) as (read_stream, write_stream, _get_session_id),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()

            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            assert "graphrag_query" in tool_names
            assert "graphrag_ingest" in tool_names

            result = await session.call_tool(
                "graphrag_query",
                {"question": "What documents are available?"},
            )
            assert result.isError is False
            assert result.structuredContent is not None
            assert "answer" in result.structuredContent
    finally:
        os.environ.pop("MCP_ENABLED", None)
        os.environ.pop("API_SERVICE_KEY", None)
        clear_settings_cache()


async def test_mcp_tool_errors_are_sanitized_before_reaching_the_client(monkeypatch) -> None:
    """A raw exception (e.g. a SQLAlchemy IntegrityError with SQL/parameter
    text embedded) must never reach an external MCP caller verbatim -- the
    mcp SDK's own call_tool() wrapper does `str(exc)` into the client-visible
    error result with no sanitization of its own."""
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("API_SERVICE_KEY", "integration-test-key")
    clear_settings_cache()
    try:
        from graph_rag.mcp.tools import TOOLS_BY_NAME, ToolSpec

        secret_marker = "INSERT INTO model_usage_events ... fk_model_usage_events_tenant_id"

        async def _leaky_handler(container, tenant, arguments):
            raise RuntimeError(secret_marker)

        monkeypatch.setitem(
            TOOLS_BY_NAME,
            "test_leaky_tool",
            ToolSpec(
                name="test_leaky_tool",
                description="test only",
                input_schema={"type": "object", "properties": {}},
                handler=_leaky_handler,
            ),
        )

        container = build_local_container()
        app = create_app(container)
        tenant_id = uuid4()
        headers = {
            "X-Api-Service-Key": "integration-test-key",
            "X-Tenant-ID": str(tenant_id),
        }

        async with (
            app.router.lifespan_context(app),
            streamablehttp_client(
                "http://mcp-test/api/v1/mcp/",
                headers=headers,
                httpx_client_factory=_client_factory(app, headers),
            ) as (read_stream, write_stream, _get_session_id),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            result = await session.call_tool("test_leaky_tool", {})
            assert result.isError is True
            error_text = " ".join(getattr(c, "text", "") for c in result.content)
            assert secret_marker not in error_text
            assert "Internal error processing tool call" in error_text
    finally:
        os.environ.pop("MCP_ENABLED", None)
        os.environ.pop("API_SERVICE_KEY", None)
        clear_settings_cache()


async def test_mcp_rejects_requests_without_a_valid_service_key(monkeypatch) -> None:
    """The transport itself (not just the client SDK's handshake) returns 401
    for a connection lacking a valid X-Api-Service-Key -- tested at the raw
    ASGI level since the MCP client SDK wraps a failed handshake in a task-group
    ExceptionGroup that's fragile to assert on directly."""
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("API_SERVICE_KEY", "integration-test-key")
    clear_settings_cache()
    try:
        container = build_local_container()
        app = create_app(container)

        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://mcp-test"
            ) as client,
        ):
            response = await client.post(
                "/api/v1/mcp/",
                headers={"Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )
            assert response.status_code == 401
    finally:
        os.environ.pop("MCP_ENABLED", None)
        os.environ.pop("API_SERVICE_KEY", None)
        clear_settings_cache()

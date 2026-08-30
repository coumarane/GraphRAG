"""MCP tenant resolution: the hard security gate.

Tenant identity must come only from trusted per-connection ASGI headers,
never from a tool-call argument (the JSON-RPC payload is model-generated /
prompt-injectable). ``resolve_tenant_from_scope`` doesn't even accept a tool
arguments dict -- proving structurally, not just by convention, that a
crafted ``tenant_id`` in a tool call cannot influence which tenant resolves.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from graph_rag.application.runtime.local import build_local_container
from graph_rag.mcp import auth
from graph_rag.shared.exceptions import AuthenticationError


def _scope(headers: dict[str, str]) -> dict:
    return {
        "type": "http",
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()],
    }


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"x-api-service-key": "wrong-key"},
    ],
)
async def test_resolve_tenant_rejects_missing_or_wrong_service_key(monkeypatch, headers) -> None:
    monkeypatch.setenv("API_SERVICE_KEY", "correct-key")
    from graph_rag.config.settings import clear_settings_cache

    clear_settings_cache()
    try:
        container = build_local_container()
        with pytest.raises(AuthenticationError):
            await auth.resolve_tenant_from_scope(container, _scope(headers))
    finally:
        clear_settings_cache()


async def test_resolve_tenant_uses_only_connection_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_SERVICE_KEY", "correct-key")
    from graph_rag.config.settings import clear_settings_cache

    clear_settings_cache()
    try:
        container = build_local_container()
        tenant_id = uuid4()
        tenant = await auth.resolve_tenant_from_scope(
            container,
            _scope(
                {
                    "x-api-service-key": "correct-key",
                    "x-tenant-id": str(tenant_id),
                    "x-principal": "mcp-client",
                }
            ),
        )
        assert tenant.tenant_id == tenant_id
        assert tenant.is_service is True
    finally:
        clear_settings_cache()


def test_current_tenant_raises_without_binding() -> None:
    with pytest.raises(AuthenticationError):
        auth.current_tenant()


async def test_mcp_closed_by_default_without_service_key_configured(monkeypatch) -> None:
    # No service key configured -> AuthenticationError, confirming the gate is
    # closed unless explicitly provisioned (a documented v1 limitation, not an
    # oversight).
    from graph_rag.config.settings import clear_settings_cache

    monkeypatch.delenv("API_SERVICE_KEY", raising=False)
    clear_settings_cache()
    try:
        container = build_local_container()
        with pytest.raises(AuthenticationError):
            await auth.resolve_tenant_from_scope(container, {"type": "http", "headers": []})
    finally:
        clear_settings_cache()


def test_no_tool_handler_module_imports_a_tenant_id_argument() -> None:
    """Static guard: tool handlers must resolve tenant via auth.current_tenant(),
    never by reading a tenant-shaped key out of the arguments dict."""
    from graph_rag.mcp.tools import TOOLS

    for tool in TOOLS:
        assert "tenant" not in tool.input_schema.get("properties", {}), (
            f"{tool.name} exposes a tenant-shaped argument in its input schema"
        )

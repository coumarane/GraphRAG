"""MCP ops introspection for the admin UI (tool list + connect hints)."""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.mcp.tools import TOOLS

MCP_ENDPOINT_PATH = "/api/v1/mcp/"

AUTH_HEADERS_REQUIRED: tuple[str, ...] = (
    "X-Api-Service-Key",
    "X-Tenant-Key",
    "X-Tenant-ID",
    "X-Principal",
)


class McpToolInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str


class McpOpsStatus(BaseModel):
    """Read-only MCP server status for operators."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    endpoint: str = MCP_ENDPOINT_PATH
    tools: list[McpToolInfo] = Field(default_factory=list)
    auth_headers_required: list[str] = Field(
        default_factory=lambda: list(AUTH_HEADERS_REQUIRED)
    )
    notes: list[str] = Field(default_factory=list)


def mcp_enabled_from_env() -> bool:
    return os.environ.get("MCP_ENABLED", "false").strip().lower() not in {
        "0",
        "false",
        "no",
        "",
    }


def build_mcp_ops_status(*, enabled: bool | None = None) -> McpOpsStatus:
    is_enabled = mcp_enabled_from_env() if enabled is None else enabled
    notes = [
        "Configure MCP clients with the trailing slash on the endpoint.",
        "Auth uses static service-key headers (not browser JWT cookies).",
        "One MCP connection is scoped to one tenant for its lifetime.",
    ]
    if not is_enabled:
        notes.insert(
            0,
            "MCP is disabled. Set MCP_ENABLED=true on the API and redeploy.",
        )
    return McpOpsStatus(
        enabled=is_enabled,
        endpoint=MCP_ENDPOINT_PATH,
        tools=[
            McpToolInfo(name=tool.name, description=tool.description) for tool in TOOLS
        ],
        auth_headers_required=list(AUTH_HEADERS_REQUIRED),
        notes=notes,
    )

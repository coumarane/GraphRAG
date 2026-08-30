"""Registry of MCP tools: name -> (input schema, handler).

Kept as a plain module-level list rather than a dynamic registry -- if the
plugin-architecture work's ``graph_rag.*`` entry-point groups are ever
extended with a ``graph_rag.mcp_tools`` group, this list is the natural
place a discovery pass would populate, but nothing here requires that today.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from graph_rag.application.runtime.container import ServiceContainer
from graph_rag.domain.tenant import TenantContext
from graph_rag.mcp.tools import documents, ingestion, retrieval, runs

ToolHandler = Callable[[ServiceContainer, TenantContext, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="graphrag_ingest",
        description="Register a document from a URL for ingestion.",
        input_schema=ingestion.INGEST_INPUT_SCHEMA,
        handler=ingestion.ingest,
    ),
    ToolSpec(
        name="graphrag_query",
        description="Ask a grounded question over documents; returns an answer with citations.",
        input_schema=retrieval.QUERY_TOOL_INPUT_SCHEMA,
        handler=retrieval.query_documents,
    ),
    ToolSpec(
        name="graphrag_retrieve",
        description="Search for evidence chunks without generating an answer.",
        input_schema=retrieval.RETRIEVE_TOOL_INPUT_SCHEMA,
        handler=retrieval.retrieve_evidence,
    ),
    ToolSpec(
        name="graphrag_inspect_document",
        description="Get document metadata, optionally including a chunk preview.",
        input_schema=documents.INSPECT_INPUT_SCHEMA,
        handler=documents.inspect_document,
    ),
    ToolSpec(
        name="graphrag_delete_document",
        description="Delete a document and its derived vectors/graph data.",
        input_schema=documents.DELETE_INPUT_SCHEMA,
        handler=documents.delete_document,
    ),
    ToolSpec(
        name="graphrag_reindex_document",
        description="Reindex a document's vectors and/or graph projection without re-uploading it.",
        input_schema=documents.REINDEX_INPUT_SCHEMA,
        handler=documents.reindex_document,
    ),
    ToolSpec(
        name="graphrag_show_run",
        description="Show an ingestion run's status and per-stage progress.",
        input_schema=runs.SHOW_RUN_INPUT_SCHEMA,
        handler=runs.show_run,
    ),
    ToolSpec(
        name="graphrag_resume_run",
        description="Resume a failed or partially completed ingestion run.",
        input_schema=runs.RESUME_RUN_INPUT_SCHEMA,
        handler=runs.resume_run,
    ),
)

TOOLS_BY_NAME: dict[str, ToolSpec] = {tool.name: tool for tool in TOOLS}

__all__ = ["TOOLS", "TOOLS_BY_NAME", "ToolSpec"]

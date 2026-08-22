"""graphrag_query / graphrag_retrieve tool handlers.

Both mirror their API route counterparts (``api/routes/retrieval.py``)
exactly for authz/quota/usage-context, sharing one ``QuotaMetric.QUERIES``
daily budget -- MCP callers are a second door into the same budget an
end-user query already draws from, not a separate allowance.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from graph_rag.application.authorization.gate import require_action
from graph_rag.application.runtime.container import ServiceContainer
from graph_rag.application.usage.context import usage_context
from graph_rag.config.settings import get_settings
from graph_rag.domain.authorization.models import Action
from graph_rag.domain.ids import new_id
from graph_rag.domain.modality import Modality
from graph_rag.domain.quotas.models import QuotaMetric
from graph_rag.domain.retrieval.enums import RetrievalMode
from graph_rag.domain.retrieval.models import QueryRequest, RetrievalFilters, RetrievalRequest
from graph_rag.domain.tenant import TenantContext
from graph_rag.mcp.tools._dispatch import quota_guard

QUERY_TOOL_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "minLength": 1},
        "mode": {
            "type": "string",
            "enum": [m.value for m in RetrievalMode],
            "default": "auto",
        },
        "document_ids": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}},
        "top_k": {"type": "integer", "minimum": 1, "maximum": 100, "default": 12},
        "graph_depth": {"type": "integer", "minimum": 0, "maximum": 10, "default": 2},
        "include_graph_paths": {"type": "boolean", "default": False},
        "rerank": {"type": "boolean", "default": True},
    },
    "required": ["question"],
}

RETRIEVE_TOOL_INPUT_SCHEMA = QUERY_TOOL_INPUT_SCHEMA


def _filters_from_args(arguments: dict[str, Any]) -> RetrievalFilters:
    return RetrievalFilters(
        document_ids=[UUID(item) for item in arguments.get("document_ids") or []],
        modalities=[Modality(item) for item in arguments.get("modalities") or []],
        tags=[str(item) for item in arguments.get("tags") or []],
        security_labels=[str(item) for item in arguments.get("security_labels") or []],
    )


def _arg_or_default(arguments: dict[str, Any], key: str, default: Any) -> Any:
    value = arguments.get(key)
    return default if value is None else value


def _common_request_kwargs(arguments: dict[str, Any]) -> dict[str, Any]:
    """Field defaults fall back to config, not hardcoded literals, so a
    tenant's configured retrieval defaults (the config composer's Retrieval
    card) apply here the same as they do for the HTTP API."""
    defaults = get_settings().retrieval
    return {
        "question": arguments["question"],
        "mode": RetrievalMode(_arg_or_default(arguments, "mode", defaults.default_mode.value)),
        "filters": _filters_from_args(arguments),
        "top_k": int(_arg_or_default(arguments, "top_k", defaults.top_k)),
        "graph_depth": int(_arg_or_default(arguments, "graph_depth", defaults.graph_depth)),
        "include_graph_paths": bool(arguments.get("include_graph_paths", False)),
        "rerank": bool(_arg_or_default(arguments, "rerank", defaults.rerank)),
    }


async def query_documents(
    container: ServiceContainer,
    tenant: TenantContext,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Grounded question-answering. Deliberately omits answer_model_override and
    raw conversation_history from the exposed schema, and skips the API
    route's conversation-thread persistence -- MCP calls are one-shot tool
    invocations, not a chat session."""
    require_action(container.require_authorization(), tenant, Action.QUERY_EXECUTE)
    async with quota_guard(container.require_quotas(), tenant, metric=QuotaMetric.QUERIES):
        with usage_context(tenant_id=tenant.tenant_id, query_id=new_id(), user_id=tenant.user_id):
            outcome = await container.require_query().query(
                tenant,
                QueryRequest(**_common_request_kwargs(arguments)),
            )
    await container.commit_db()
    return outcome.response.model_dump(mode="json")


async def retrieve_evidence(
    container: ServiceContainer,
    tenant: TenantContext,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Evidence search without answer generation."""
    require_action(container.require_authorization(), tenant, Action.QUERY_EXECUTE)
    async with quota_guard(container.require_quotas(), tenant, metric=QuotaMetric.QUERIES):
        with usage_context(tenant_id=tenant.tenant_id, query_id=new_id(), user_id=tenant.user_id):
            outcome = await container.require_retrieve().retrieve(
                tenant,
                RetrievalRequest(**_common_request_kwargs(arguments)),
            )
    await container.commit_db()
    return outcome.result.model_dump(mode="json")

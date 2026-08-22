"""MCP tool handlers: authz/quota gates fire before the service call.

``RegisterSourceService`` self-enforces authorization/quotas internally
(``application/ingestion/register_source.py``) -- every other handler here
must replicate its mirrored API route's require_action -> quota reserve ->
service call sequence explicitly. These tests prove the gate genuinely runs
first, not just that the end-to-end result looks right.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from graph_rag.application.runtime.local import build_local_container
from graph_rag.domain.tenant import TenantContext
from graph_rag.mcp.tools import TOOLS_BY_NAME


def _service_tenant() -> TenantContext:
    return TenantContext(
        tenant_id=uuid4(),
        tenant_key="demo",
        principal="mcp-client",
        is_service=True,
    )


class _CallOrderSpy:
    """Wraps a real authorization/quota service, recording call order."""

    def __init__(self, target, calls: list[str], label: str) -> None:
        self._target = target
        self._calls = calls
        self._label = label

    def __getattr__(self, name: str):
        attr = getattr(self._target, name)
        if not callable(attr):
            return attr

        def wrapper(*args, **kwargs):
            self._calls.append(self._label)
            return attr(*args, **kwargs)

        return wrapper


async def test_query_checks_authorization_before_reserving_quota_before_calling_service() -> None:
    container = build_local_container()
    calls: list[str] = []
    container.authorization = _CallOrderSpy(container.authorization, calls, "authz")
    container.quotas = _CallOrderSpy(container.quotas, calls, "quota")

    tenant = _service_tenant()
    spec = TOOLS_BY_NAME["graphrag_query"]
    result = await spec.handler(container, tenant, {"question": "What is in the documents?"})

    assert calls[:2] == ["authz", "quota"]
    assert "answer" in result


async def test_retrieve_checks_authorization_before_reserving_quota() -> None:
    container = build_local_container()
    calls: list[str] = []
    container.authorization = _CallOrderSpy(container.authorization, calls, "authz")
    container.quotas = _CallOrderSpy(container.quotas, calls, "quota")

    tenant = _service_tenant()
    spec = TOOLS_BY_NAME["graphrag_retrieve"]
    await spec.handler(container, tenant, {"question": "anything"})

    assert calls[:2] == ["authz", "quota"]


async def test_delete_document_checks_authorization_before_service_call() -> None:
    container = build_local_container()
    calls: list[str] = []
    container.authorization = _CallOrderSpy(container.authorization, calls, "authz")

    tenant = _service_tenant()
    document_id = uuid4()
    spec = TOOLS_BY_NAME["graphrag_delete_document"]

    from graph_rag.shared.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        await spec.handler(container, tenant, {"document_id": str(document_id)})

    # NotFoundError fires before require_action (document must exist to
    # evaluate a document-scoped ABAC resource) -- confirms the 404-before-authz
    # ordering matches api/routes/documents.py::delete_document exactly.
    assert "authz" not in calls


async def test_reindex_document_rejects_unknown_scope() -> None:
    from graph_rag.shared.exceptions import ValidationError

    container = build_local_container()
    tenant = _service_tenant()
    spec = TOOLS_BY_NAME["graphrag_reindex_document"]

    with pytest.raises(ValidationError):
        await spec.handler(container, tenant, {"document_id": str(uuid4()), "scope": "bogus"})


def test_ingest_handler_does_not_call_require_action_itself() -> None:
    """RegisterSourceService self-enforces DOCUMENT_UPLOAD internally; the MCP
    handler must not re-wrap it or the check double-fires."""
    from graph_rag.mcp.tools import ingestion

    assert "require_action" not in dir(ingestion)
    assert "gate" not in dir(ingestion)


def test_tool_registry_has_no_worker_or_admin_introspection_tools() -> None:
    from graph_rag.mcp.tools import TOOLS_BY_NAME

    assert "graphrag_worker" not in TOOLS_BY_NAME
    assert "graphrag_plugins_list" not in TOOLS_BY_NAME

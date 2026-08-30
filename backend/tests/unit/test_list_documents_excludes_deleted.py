"""``DocumentRepository.list_documents`` must omit soft-deleted rows.

Hard-delete is the preferred path, but the fallback soft-delete and any
legacy ``status=deleted`` rows must not appear in list results or totals.
"""

from __future__ import annotations

import pytest

from graph_rag.domain.ids import new_id
from graph_rag.domain.ingestion.records import DocumentRecord
from graph_rag.domain.ingestion.stages import DocumentLifecycleStatus
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.memory.lifecycle import InMemoryDocumentRepository


@pytest.mark.asyncio
async def test_memory_list_documents_excludes_deleted_and_counts_active_only() -> None:
    repo = InMemoryDocumentRepository()
    tenant_id = new_id()
    tenant = TenantContext(tenant_id=tenant_id, tenant_key="demo", roles=("admin",))

    active_id = new_id()
    deleted_id = new_id()
    await repo.create_document(
        tenant,
        DocumentRecord(
            document_id=active_id,
            tenant_id=tenant_id,
            title="active",
            status=DocumentLifecycleStatus.READY,
        ),
    )
    await repo.create_document(
        tenant,
        DocumentRecord(
            document_id=deleted_id,
            tenant_id=tenant_id,
            title="gone",
            status=DocumentLifecycleStatus.DELETED,
        ),
    )

    items, total = await repo.list_documents(tenant, offset=0, limit=50)
    assert total == 1
    assert [item.document_id for item in items] == [active_id]
    # Direct get still works for soft-deleted rows (detail / authz paths).
    assert await repo.get_document(tenant, deleted_id) is not None

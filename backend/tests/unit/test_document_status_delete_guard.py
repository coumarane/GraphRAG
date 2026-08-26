"""A deleted document must never be resurrected by a stray status update.

Regression test for an incident where a long-running ingestion run
outlived a document's deletion by many hours, eventually failed (its
original file having just been purged), and its ordinary failure-handling
path -- ``ProcessRegisteredDocumentService._set_document_status`` --
unconditionally overwrote the document's status, flipping it from DELETED
back to FAILED and making a deleted document reappear in the UI.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from graph_rag.application.runtime import build_local_container
from graph_rag.domain.ids import content_sha256_hex, new_id
from graph_rag.domain.ingestion.records import DocumentRecord, DocumentVersionRecord
from graph_rag.domain.ingestion.stages import DocumentLifecycleStatus


@pytest.mark.asyncio
async def test_set_document_status_is_a_no_op_once_deleted() -> None:
    container = build_local_container()
    tenant = await container.resolve_tenant(tenant_key="demo")
    document_id = new_id()
    version_id = new_id()
    assert container.document_repo is not None
    assert container.process_ingestion is not None

    await container.document_repo.create_document(
        tenant,
        DocumentRecord(
            document_id=document_id,
            tenant_id=tenant.tenant_id,
            title="already-deleted",
            status=DocumentLifecycleStatus.DELETED,
            current_version_id=None,
        ),
    )
    await container.document_repo.create_version(
        tenant,
        DocumentVersionRecord(
            version_id=version_id,
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_number=1,
            source_filename="r.pdf",
            mime_type="application/pdf",
            content_hash=content_sha256_hex("r"),
            status=DocumentLifecycleStatus.DELETED,
        ),
    )

    await container.process_ingestion._set_document_status(
        tenant,
        document_id,
        DocumentLifecycleStatus.FAILED,
        updated_at=datetime.now(UTC),
    )

    document = await container.document_repo.get_document(tenant, document_id)
    assert document is not None
    assert document.status is DocumentLifecycleStatus.DELETED

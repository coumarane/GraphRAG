"""Enqueue an ingestion run onto the transactional outbox."""

from __future__ import annotations

from uuid import UUID

from graph_rag.domain.ingestion.outbox import (
    INGEST_QUEUED_EVENT,
    OutboxEventRecord,
    ingest_outbox_event_id,
)
from graph_rag.domain.ingestion.records import IngestionRunRecord
from graph_rag.domain.tenant import TenantContext


async def enqueue_ingest_run(
    outbox: object,
    *,
    tenant: TenantContext,
    run: IngestionRunRecord,
) -> OutboxEventRecord:
    """Insert/upsert ingest.queued in the same DB transaction as the run."""
    event = OutboxEventRecord(
        outbox_event_id=ingest_outbox_event_id(
            tenant_id=tenant.tenant_id,
            ingestion_run_id=run.ingestion_run_id,
        ),
        tenant_id=tenant.tenant_id,
        event_type=INGEST_QUEUED_EVENT,
        aggregate_id=run.ingestion_run_id,
        payload={
            "task_id": str(run.ingestion_run_id),
            "tenant_id": str(tenant.tenant_id),
            "ingestion_run_id": str(run.ingestion_run_id),
            "document_id": str(run.document_id),
            "version_id": str(run.version_id),
            "content_hash": run.content_hash or "",
            "config_fingerprint": run.config_fingerprint or "",
            "correlation_id": run.correlation_id,
            "outbox_event_id": str(
                ingest_outbox_event_id(
                    tenant_id=tenant.tenant_id,
                    ingestion_run_id=run.ingestion_run_id,
                )
            ),
        },
    )
    return await outbox.upsert(event)


async def enqueue_ingest_ids(
    outbox: object,
    *,
    tenant: TenantContext,
    ingestion_run_id: UUID,
    document_id: UUID,
    version_id: UUID,
    content_hash: str,
    config_fingerprint: str,
    correlation_id: str | None,
) -> OutboxEventRecord:
    run = IngestionRunRecord(
        ingestion_run_id=ingestion_run_id,
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        content_hash=content_hash,
        config_fingerprint=config_fingerprint,
        correlation_id=correlation_id,
    )
    return await enqueue_ingest_run(outbox, tenant=tenant, run=run)

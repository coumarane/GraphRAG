"""An unpublished outbox row is delivered once after the publisher runs again."""

from __future__ import annotations

from uuid import uuid4

import pytest
import redis.asyncio as redis_async

from graph_rag.application.ingestion.enqueue import enqueue_ingest_run
from graph_rag.application.ingestion.outbox_publisher import OutboxPublisher
from graph_rag.domain.ids import new_id
from graph_rag.domain.ingestion.records import IngestionRunRecord
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.outbox import InMemoryOutboxStore
from graph_rag.infrastructure.persistence.redis.streams import RedisStreamIngestionQueue


@pytest.mark.integration
@pytest.mark.asyncio
async def test_republish_after_restart_is_exactly_once(compose_redis: str) -> None:
    client = redis_async.from_url(compose_redis, decode_responses=False)
    queue = RedisStreamIngestionQueue(
        client,
        stream_key=f"outbox-{uuid4().hex}",
        group_name="workers",
        consumer_name="publisher",
    )
    outbox = InMemoryOutboxStore()
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    run = IngestionRunRecord(
        ingestion_run_id=new_id(),
        tenant_id=tenant.tenant_id,
        document_id=new_id(),
        version_id=new_id(),
        content_hash="c" * 64,
        config_fingerprint="fp-v1",
    )
    event = await enqueue_ingest_run(outbox, tenant=tenant, run=run)
    publisher = OutboxPublisher(outbox, queue)
    assert await publisher.publish_once() == 1
    stored = await outbox.get(event.outbox_event_id)
    assert stored is not None
    first_id = stored.stream_message_id
    stored.published_at = None
    assert await publisher.publish_once() == 1
    again = await outbox.get(event.outbox_event_id)
    assert again is not None
    assert again.stream_message_id == first_id
    assert await queue.depth() == 1
    await client.aclose()

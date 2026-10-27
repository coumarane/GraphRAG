# ADR 0002: Fail closed when the ingest queue cannot be opened

**Status**: Accepted for feature `001-reliable-upload-ingestion`  
**Date**: 2026-10-27

## Context

Acceptance is a Postgres commit that includes one `ingest.queued` outbox row. `OutboxPublisher` copies that row to Redis after commit. `runtime.py` today swallows a failure to construct the Redis client and uses an in-memory queue. That queue dies with the process, so a committed job can disappear. Constitution Principle III requires the committed task to survive on the existing outbox and Redis path.

## Decision

When `INGEST_QUEUE_BACKEND` is `redis`, or the metadata store is Postgres, the API and the worker refuse to start if the Redis client cannot be opened. The exception type is logged. The in-memory queue remains only for unit tests and an explicit memory backend. The OVH API manifest sets `INGEST_EXECUTION=worker` and `INGEST_QUEUE_BACKEND=redis`, matching the worker manifest and Compose.

No new broker is introduced. Ack, reclaim, bounded retry, and dead letter stay in `IngestionWorker`.

## Consequences

- If Redis is down, the new API does not become ready. That is the intended failure. The previous image, which could accept a job into memory, is the rollback image.
- A crash after commit and before Redis accepts the message leaves the outbox row unpublished. The publisher sends it once Redis is back.

## Evidence

- `backend/src/graph_rag/application/runtime/runtime.py` falls back to `InMemoryStreamIngestionQueue` on client construction failure.
- `backend/alembic/versions/0006_ingestion_outbox.py` already stores the outbox.
- `infra/k8s/worker/deployment.yaml` already sets the Redis queue backend.

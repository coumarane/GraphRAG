# Implementation Plan: Reliable Document Upload and Ingestion

**Branch**: `001-reliable-upload-ingestion` | **Date**: 2026-10-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-reliable-upload-ingestion/spec.md`

## Summary

Members upload a file without the web process holding the bytes. The API reserves a tenant-scoped object key and a Postgres quota reservation, the browser writes the object with a short-lived URL, and completion streams that object once to verify it. Acceptance is a single Postgres commit that inserts the ingestion run and one outbox row. The existing publisher, Redis stream, worker, stage machine, and dead-letter path then run unchanged. The upload screen stops waiting when progress fails, stalls, or finishes. The OVH Kubernetes manifests gain explicit queue settings and worker probes. Azure remains Key Vault plus optional Blob storage, not the compute cluster.

## Technical Context

**Language/Version**: Python 3.13 (`graph-rag`, `requires-python >=3.13,<3.14`); Next.js frontend already in `frontend/`

**Primary Dependencies**: FastAPI, Typer, SQLAlchemy 2 async, Alembic, Pydantic v2, existing MinIO and Azure Blob adapters, Redis Streams client, existing outbox publisher and ingestion worker

**Storage**: PostgreSQL (sessions, runs, outbox, quotas), existing object store (MinIO or Azure Blob via `OBJECT_STORE_BACKEND`), Redis Streams for delivery only

**Testing**: pytest unit tests; pytest integration tests against Postgres, Redis, and MinIO; Azurite for the Azure Blob adapter; frontend upload-page test for the spinner

**Target Platform**: OVH Kubernetes for the API, web, and worker Deployments. Local Docker Compose for validation. Not Azure Kubernetes.

**Project Type**: Existing web application (`backend/` + `frontend/` + `infra/k8s/`)

**Performance Goals**: Accept or reject a 100 MB file within 30 seconds. Web process memory stays flat while the object is written. Two concurrent 100 MB uploads do not kill the web pod. A non-terminal run with no heartbeat for 2 minutes is shown as stalled.

**Constraints**: Do not replace the stage pipeline. Do not add a broker, an upload service, or MCP tools. Published `POST /api/v1/documents/ingest` fields stay. No production access. Queue-client failure must refuse startup, not accept a job. Presigned write URLs are not logged.

**Scale/Scope**: Current API (2 replicas) and worker (1 replica) on the OVH cluster. Shared quotas across those API replicas. Worker replica count is unchanged.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Result |
| --- | --- | --- |
| I. Clean architecture and compatible interfaces | New behavior extends `ObjectStore`, `QuotaService`, and the existing ingest use cases. Domain code does not import store SDKs. `/api/v1` ingest fields are not removed. Structural choices are recorded in `docs/adr/0001`, `0002`, and `0003`. | Pass |
| II. Security by design | Tenant prefix on every key and URL. ABAC unchanged. MIME from bytes, size cap, archive checks retained. The write URL is the constitution 2.0.0 staging exception: one member, one staging key, at most 15 minutes, never the final object. Secrets and write URLs stay out of logs. Tests use local fixtures. | Pass |
| III. Reliable ingestion | Outbox commit is the acceptance boundary. Retries stop at the existing bound of 3, then dead letter. No silent in-memory queue when Redis is required. | Pass |
| IV. Grounded GraphRAG | Retrieval and citation behavior are untouched. | Pass |
| V. Provider abstraction | No new model provider and no MCP tool. | Pass |
| VI. Observability and cost | This feature adds run progress and session counters. Cross-process traces are not exportable. That control is not implemented. Recorded exception in constitution 2.0.0, owner Enterprise RAG team, deadline 2027-01-31. | Exception |
| VII. Automated delivery and recovery | This feature adds worker probes and Compose integration tests. Practiced restore of Postgres, Qdrant, Neo4j, and object storage is not implemented. Azure Blob soft-delete is not a restore drill. Recorded exception in constitution 2.0.0, owner Enterprise RAG team, deadline 2027-01-31. | Exception |
| VIII. FinOps | No new database, queue, or cluster add-on. Worker replicas stay 1. | Pass |
| IX. Spec-driven delivery | This plan, research, data model, and contracts trace to `spec.md`. | Pass |

Gates VI and VII are exceptions, not passes. The exceptions do not waive tenant isolation, citation grounding, or secret handling. Complexity Tracking records them.

## Project Structure

### Documentation (this feature)

```text
specs/001-reliable-upload-ingestion/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── upload-session.schema.yaml
│   └── ingestion-progress.schema.yaml
└── tasks.md              # created later by /speckit-tasks
```

### Source Code (repository root)

```text
backend/src/graph_rag/
├── api/routes/documents.py          # session routes; ingest route kept
├── api/schemas/common.py            # additive progress fields
├── application/ingestion/           # session use case, completion, title rule
├── application/quotas/              # Postgres-backed QuotaService
├── application/runtime/runtime.py   # fail closed when Redis is required
├── domain/storage/protocols.py      # presign_put + streaming read
├── domain/ingestion/stages.py       # unchanged; no uploading document status
├── infrastructure/persistence/minio/
├── infrastructure/persistence/azure_blob/
├── infrastructure/persistence/postgres/
├── infrastructure/workers/          # health port on the existing process
└── alembic/versions/0013_upload_sessions.py

backend/tests/integration/          # real Postgres, Redis, MinIO, failure injection
frontend/src/app/upload/            # session flow; spinner stops on error
frontend/src/app/api/               # JSON proxies only; ingest route no longer carries bytes
infra/k8s/api/deployment.yaml       # explicit INGEST_EXECUTION and INGEST_QUEUE_BACKEND
infra/k8s/worker/deployment.yaml    # probes on port 8081; limits unchanged
```

**Structure Decision**: Extend the current `backend/`, `frontend/`, and `infra/k8s/` tree. The worker command remains `enterprise-rag worker` until that manifest is switched on its own, which is outside this feature.

## Design

### Data flow

```text
Member
  |  POST JSON (name, size, title) through the web app
  v
API  -- Postgres transaction -->
       upload_sessions row only (no document row)
       quota reservations (row-locked counters)
  |  returns write URL for that tenant staging key only
  v
Member PUT bytes --> MinIO (Compose / MinIO-backed env, CORS for the web origin)
                 \-> Azure Blob (only when OBJECT_STORE_BACKEND=azure_blob)
  |  POST JSON complete
  v
API streams the staging object (hash, type, size, archive checks)
  |  copy to final key, store size and etag, delete staging
  |  one transaction:
  |    document + version + content hash + etag
  |    ingestion run + existing stage rows
  |    one ingest.queued outbox row
  |    quota commit
  |    document status=ingesting
  v
OutboxPublisher (already on the API) -- after commit --> Redis Stream
  v
Existing worker claims, runs the current stages, acks after durable success
  or writes a dead letter and then acks
  v
GET /api/v1/ingestion-runs/{id}
  progress_state from status + heartbeat_at
  v
Upload screen stops on ready, failed, stalled, or any poll error
```

A crash before the completion commit leaves a `pending` session, no document, and no outbox row. The sweep expires it, deletes the staging object, and releases the quota. A crash after the commit leaves a durable outbox row and one final object; the publisher sends the row when Redis is back. A crash after Redis accepts the message and before ack is the existing reclaim path. The worker skips stages already completed for that fingerprint and dead-letters the failure that exhausts `RetryPolicy.max_attempts` of 3.

The existing multipart ingest route stays for the CLI. It still registers through `RegisterSourceService`, then uses the same outbox. It must not be what the upload screen calls.

### Component changes

- **Upload session use case**: new application service beside `RegisterSourceService`. It does not call the parser.
- **Object store port**: `presign_put` for a staging key, copy to the final key, and an async byte iterator. MinIO and Azure Blob adapters implement both. Memory adapter implements both for unit tests. Prefix checks stay in `assert_tenant_object_prefix`. Final-object retention is applied when the backend supports it. See `docs/adr/0003-immutable-accepted-originals.md`.
- **Queue wiring**: if `INGEST_QUEUE_BACKEND` is `redis` or the metadata store is Postgres, a failed Redis client constructor aborts startup and logs the exception type. The in-memory queue remains for unit tests and the explicit memory backend only.
- **API and worker manifests**: both init containers append `INGEST_EXECUTION=worker` and `INGEST_QUEUE_BACKEND=redis`, matching Compose. This removes the API's inferred setting on the OVH cluster.
- **Quotas**: `PostgresQuotaService` implements the existing `QuotaService` port against `usage_counters` and `quota_reservations`. Runtime selects it when the metadata store is Postgres.
- **Title**: `_title_from_source` uses a non-empty request title first.
- **Worker**: bind `8081` in the worker process. Readiness checks Postgres, Redis, and the object store. Liveness is the process. Probes, existing resource limits, and `replicas: 1` in `infra/k8s/worker/deployment.yaml`.
- **Frontend**: `buildIngestFormData` is replaced for the screen by create, PUT, complete. Poll handler surfaces non-OK responses and `progress_state` of `stalled` or `failed`.

### Migration

Revision `0013_upload_sessions` revises `0012_document_search`.

Upgrade creates `upload_sessions` and, if absent, nullable `etag` and `object_version_id` on document versions. Indexes match [data-model.md](./data-model.md). It does not alter `documents` status values, `ingestion_runs`, `outbox_events`, or quota tables. There is no `uploading` document status.

Downgrade drops `upload_sessions` and the nullable `etag` and `object_version_id` columns added by this revision. Existing documents, runs, and their other columns stay. Do not downgrade while a session is `pending`.

Apply with the existing migration job on the OVH cluster after the artifact is reviewed. This plan does not run that job.

### Rollout

1. Deploy the migration. Old API builds ignore the new table.
2. Deploy the API and worker images together, with the explicit queue settings and the worker probes. Confirm Redis is reachable first. If Redis is down, the new API must not become ready.
3. Deploy the web image that uses the session flow.
4. Watch `ingest_publish_failures_total`, worker readiness, and new runs leaving `pending`.
5. Before the web image is served to members, an operator sets Azure Blob CORS for the web origin when `OBJECT_STORE_BACKEND=azure_blob`. That step is not part of implementation and is not applied to production by this plan. Local MinIO CORS is in Compose.

Rollback:

1. Deploy the previous web image so the screen uses multipart ingest again.
2. Deploy the previous API and worker images if the fail-closed queue startup is the problem. The old images still understand existing documents.
3. Leave revision `0013` in place unless a downgrade is required. Downgrade drops `upload_sessions` and the nullable version columns from that revision, and must wait until no session is `pending`.

Do not roll back by deleting documents, runs, or objects.

### Observability

- Structured logs for session create, complete, expire, and queue startup failure. Include tenant id, upload id, and run id. Omit write URLs and bytes.
- Keep the existing `ingest_publish_failures_total` and queue-depth gauges.
- Add counters: `upload_sessions_created_total`, `upload_sessions_completed_total`, `upload_sessions_rejected_total`, `upload_sessions_expired_total`.
- Worker readiness failure is the signal that processing cannot start. A stalled run is the member-visible signal when the worker is up but a run is not advancing.

### Acceptance

Matches [spec.md](./spec.md) SC-001 through SC-009 and [quickstart.md](./quickstart.md):

- 100 MB acceptance does not depend on the web pod holding the file.
- One completion transaction, one outbox row, one original after retry.
- Duplicate bytes and cross-tenant access behave as the spec states.
- Spinner stops on poll failure and on a 2-minute stall.
- Organization quota holds across two API processes.
- Worker manifest has a liveness probe, a readiness probe, and the current resource limits.

## Constitution Check (post-design)

Re-checked against the contracts, data model, and ADRs. Gates I–V, VIII, and IX pass. Gates VI and VII stay Exception. No new service, no published-field removal, no production access, and no silent accept path were introduced. The design does not claim that traces are exported or that restore drills exist.

## Complexity Tracking

| Exception | Why it is not a pass | Why the feature still proceeds | Deadline |
| --- | --- | --- | --- |
| VI. Traces are in-process only | No OTLP exporter is attached to the API or worker | Logs, `/metrics`, and stored run status cover this feature's acceptance | 2027-01-31, Enterprise RAG team |
| VII. Restore is not practiced | No backup job or recorded drill for Postgres, Qdrant, Neo4j, or object storage | This feature does not add a store. Soft-delete on Azure Blob is not treated as the drill | 2027-01-31, Enterprise RAG team |

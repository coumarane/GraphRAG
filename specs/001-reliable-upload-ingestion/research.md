# Research: Reliable Document Upload and Ingestion

## Decision: Staging key, then an immutable final object

**Decision**: The write URL names only a staging key. Completion copies that object to the final original key, stores byte size and etag, deletes the staging object, and only then commits the document. MinIO retention on the final key, or an Azure Blob immutability policy, is applied when the backend supports it. The protected final key is required even when retention is not available. A later PUT with the write URL, or an etag mismatch, is refused. See `docs/adr/0003-immutable-accepted-originals.md`.

**Rationale**: Constitution 2.0.0 allows the write URL only for a staging object and forbids that URL from changing accepted bytes. Both stores can overwrite an object while a URL is unexpired. Copying to a key the URL cannot name closes that hole without a new storage product.

**Alternatives considered**:

- Pin etag on the same key the URL writes. Rejected. The client can still overwrite that key before the worker reads it.
- A new immutable bucket. Rejected. The existing bucket and tenant prefix already exist.

## Decision: Browser CORS on the existing bucket

**Decision**: Local MinIO CORS allows PUT from the Compose web origin and from `http://localhost:3000`. It does not set a public read or write policy. Azure Blob CORS for the production web origin is an operator checklist item in `rollout.md`, applied only with the reviewed release, not during implementation. A test loads the upload screen origin and asserts the file PUT does not go to the Next.js ingest route.

**Rationale**: Without CORS the direct upload cannot succeed from the browser. The web memory bug would remain.

**Alternatives considered**:

- Proxy the bytes through the API to avoid CORS. Rejected as the primary path. It puts the file back on an application process. Kept for the CLI and for remote URL intake.

## Decision: Remote URL uses the existing safe fetch

**Decision**: A session may carry `source_url` instead of a staging upload. The API uses the existing HTTPS allow-list, private-address block, and size cap, then writes the final object and commits the same outbox transaction. No document row exists if the fetch or the checks fail. This is not a second pipeline.

**Rationale**: FR-016 is in the spec. The safe fetcher already exists. The upload screen's file path stays the direct PUT.

**Alternatives considered**:

- Drop remote URL from this feature. Rejected. The spec includes it, and the fetcher is already shipped.

## Decision: Direct upload to the existing object store

**Decision**: The browser uploads bytes with a short-lived write URL for the staging key only, as in the staging decision above and `docs/adr/0001-direct-object-upload.md`. The Next.js route forwards only small JSON. The API streams the staging object once on completion. It does not hold the whole file. Constitution version 2.0.0 is what allows that URL in the member's response. Principles VI and VII have time-bounded exceptions in the constitution through 2027-01-31. Those controls are not implemented. See `docs/adr/0002-fail-closed-ingest-queue.md`.

**Rationale**: The web Deployment allows 512Mi for the whole process. `frontend/src/app/api/ingest/route.ts` reads the entire multipart body and forwards a second copy, while the product allows 100 MB. That is the confirmed acceptance failure. The API Deployment allows 2Gi, and both `MinioObjectStore` and `AzureBlobObjectStore` already enforce tenant prefixes and can issue a read URL (`presign_get`). A write URL is the same port, not a new storage product. Streaming the object on completion keeps MIME-from-bytes, SHA-256, and archive checks without a second copy in the web process.

**Alternatives considered**:

- Stream the multipart body through Next.js. Rejected. The web pod would still stay on the byte path for the whole transfer and would still sit under the 512Mi cap and the public gateway timeout.
- Stream the multipart body only through the API and leave the browser talking to Next.js. Rejected as the primary path. It fixes the web cap only if Next.js never buffers, which the current route does. Kept as the compatibility path for the existing `POST /api/v1/documents/ingest` callers (CLI and older clients), which already land on the API.
- Add a dedicated upload service. Rejected. Constitution Principle VIII forbids a new service when MinIO, Azure Blob, and the API can do this.

## Decision: Acceptance is a Postgres commit that includes the outbox row

**Decision**: A document is accepted only when one database transaction stores the version, the ingestion run, the stage rows, and one `ingest.queued` outbox row, then commits. The existing `OutboxPublisher` copies that row to Redis after commit. If the queue client cannot be opened, the API and the worker refuse to start.

**Rationale**: `enqueue_ingest_ids` and `outbox_events` (migration `0006_ingestion_outbox`) already implement this. The gap is `runtime.py`, which swallows queue-client errors and falls back to `InMemoryStreamIngestionQueue`. That queue dies with the process, so a 202 can refer to a job the worker will never see. Redis Streams, ack-after-durable-success, reclaim, and dead letters already exist in `IngestionWorker` and are covered by `backend/tests/integration/test_ingest_worker_reliability.py` against in-memory stand-ins.

**Alternatives considered**:

- Publish to Redis inside the request, before commit. Rejected. A crash after publish and before commit creates a job with no run, or a commit with no job.
- Replace Redis with another broker. Rejected. The worker, compose file, and OVH worker manifest already use Redis.

## Decision: Keep the current stage machine

**Decision**: No stage is added, removed, or reordered. Completion enqueues the existing run. The worker keeps `run_document_pipeline`, content fingerprints, idempotency keys, and dead letters.

**Rationale**: The spec requires reuse. Stages already live in `IngestionStageName`. Resume and duplicate-original behavior are properties of that machine and of `RegisterSourceService`, not of a new orchestrator.

**Alternatives considered**:

- A new "upload" stage inside the worker. Rejected. The original must exist before the run is queued, so the worker never sees a missing file. A pending upload is an intake session, not a pipeline stage.

## Decision: Derive stalled progress from the existing heartbeat

**Decision**: `GET /api/v1/ingestion-runs/{id}` gains additive fields. `progress_state` is `stalled` when a non-terminal run has no heartbeat, or `heartbeat_at` is older than 2 minutes. The upload screen stops the spinner on any failed status check and on `stalled` or `failed`.

**Rationale**: `heartbeat_at` is already on `ingestion_runs` and `ingestion_stages` (migration `0006`). The spinner bug is in `frontend/src/app/upload/page.tsx`, which returns early when the poll is not OK. No new status column is required for the member-visible rule. Terminal states stay the existing enum.

**Alternatives considered**:

- A new persisted `stalled` status written by a sweeper. Rejected for the member view. It would race with the worker heartbeat. A derived field is enough. Operators still see `pending` or `running` plus the heartbeat timestamp.

## Decision: Shared quotas use the existing Postgres quota tables

**Decision**: When the metadata store is Postgres, reserve, commit, and release take a row lock on `usage_counters` for `(tenant_id, metric, period_key)` and write `quota_reservations`. The in-memory quota service remains only for unit tests and the memory backend.

**Rationale**: Migration `0005_abac_quotas` already created `quota_plans`, `quota_assignments`, `usage_counters`, `quota_reservations`, and `quota_usage_events`. `QuotaService` is already a domain port. `build_local_container` always constructs `InMemoryQuotaService`, so two API replicas do not share a budget. No new database.

**Alternatives considered**:

- Redis counters. Rejected. Quotas must commit or roll back with the upload transaction. Postgres row locks do that. Redis would be a second source of truth.
- Leave in-memory quotas. Rejected. It fails FR-015.

## Decision: Worker health is an HTTP port on the existing worker process

**Decision**: The worker process listens on port 8081. Liveness is "process is up". Readiness checks Postgres, Redis, and the configured object store, reusing the API readiness idea. `infra/k8s/worker/deployment.yaml` gains probes and keeps its current CPU and memory limits. Replica count stays 1 until queue depth justifies a change.

**Rationale**: The worker command is a poll loop with no probe. The API and web Deployments already have HTTP probes. A sidecar or a new health service would add a moving part. An exec probe that only checks the process would stay green while Redis or Postgres is unreachable.

**Alternatives considered**:

- Kubernetes exec probe of the process only. Rejected as the sole check. It does not show a dead dependency.
- Raise the worker to more replicas in this feature. Rejected. Constitution Principle VIII requires queue-depth evidence first.

## Decision: OVH Kubernetes stays the runtime; Azure stays the secret and optional blob dependency

**Decision**: Manifest changes land in `infra/k8s/` for the OVH cluster (API, worker, web). Object storage follows `OBJECT_STORE_BACKEND`: MinIO for Compose and any OVH environment still on MinIO; Azure Blob when that variable is `azure_blob`. Both adapters gain `presign_put` and a streaming read. This feature does not add Azure Kubernetes, and it does not change the Azure Terraform storage account except to record a later CORS allow-list for the web origin. That CORS change is an operator step, not part of this plan's implementation.

**Rationale**: `infra/k8s/api/deployment.yaml` and `infra/k8s/worker/deployment.yaml` schedule onto the OVH cluster and inject Azure Key Vault files. README states production on that cluster can use Azure Blob instead of MinIO. Treating "Azure" as the compute platform would target the wrong cluster.

**Alternatives considered**:

- Presign only for MinIO. Rejected. An OVH deployment with `OBJECT_STORE_BACKEND=azure_blob` would still buffer uploads.
- Presign only for Azure Blob. Rejected. Local Compose and any MinIO-backed environment would keep the broken path.

## Decision: Additive API, existing ingest kept

**Decision**: Add `POST /api/v1/documents/uploads` and `POST /api/v1/documents/uploads/{upload_id}/complete`. Keep `POST /api/v1/documents/ingest` and its response fields. The upload screen switches to the new pair. CLI and the existing MCP ingest tool keep calling the current register path. This feature does not add MCP tools.

**Rationale**: Constitution Principle I forbids removing or renaming published `/api/v1` fields. The user forbade new MCP use for deterministic ingestion. The existing ingest route remains valid for callers that already hold the bytes on the server.

**Alternatives considered**:

- Replace `POST /documents/ingest` with the session flow. Rejected. It breaks current CLI and tests.

## Decision: Honor the typed title

**Decision**: If the member submits a non-empty title, store that title. If the title is blank, keep today's file-name fallback.

**Rationale**: `RegisterSourceService._title_from_source` ignores the request title whenever `source_filename` is set. That contradicts FR-005. Existing stored titles are not rewritten.

**Alternatives considered**:

- Always prefer the file name. Rejected. The spec requires the typed title.

## Decision: Tests use Compose dependencies, not the OVH cluster

**Decision**: Integration tests run against Postgres, Redis, and MinIO from Docker Compose or Testcontainers. One test profile exercises the Azure Blob adapter with the Azurite stand-in, not the production storage account. Failure injection covers Redis refused at startup, worker crash before ack, double complete, expired upload, cross-tenant object key, and two concurrent quota reserves. The frontend spinner is covered by a component test. No test points at production.

**Rationale**: Constitution Principle II forbids reading production data or secrets. The existing integration module uses in-memory fakes only, so it cannot catch the silent queue fallback or a real transaction rollback.

**Alternatives considered**:

- A smoke test against the OVH cluster. Rejected for this plan. It would require production or shared-cluster access, which this work forbids.

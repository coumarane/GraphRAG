---
description: "Task list for reliable document upload and ingestion"
---

# Tasks: Reliable Document Upload and Ingestion

**Input**: Design documents from `/specs/001-reliable-upload-ingestion/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md, constitution

**Tests**: Included. The spec and the task request require automated tests beside the implementation. Write each test so it fails before the code it names is changed.

**Organization**: Tasks follow user-story priority. The eight requested milestones map onto these phases as noted in Dependencies.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story phase only (`[US1]`–`[US4]`)
- Every task names a file path

## Path Conventions

- Backend: `backend/src/graph_rag/`, `backend/tests/`, `backend/alembic/`
- Frontend: `frontend/src/`
- OVH manifests: `infra/k8s/`
- Local validation uses Docker Compose. Production OVH apply is a checklist only and is not an implementation step.

## Reuse (do not replace)

- `RegisterSourceService` and `POST /api/v1/documents/ingest` in `backend/src/graph_rag/api/routes/documents.py` stay for the CLI. Response fields on `IngestAcceptedResponse` stay.
- `enqueue_ingest_ids` in `backend/src/graph_rag/application/ingestion/enqueue.py`, `OutboxPublisher` in `backend/src/graph_rag/application/ingestion/outbox_publisher.py`, and `IngestionWorker` in `backend/src/graph_rag/infrastructure/workers/ingestion_worker.py` stay the delivery path.
- Stage order in `backend/src/graph_rag/domain/ingestion/stages.py` is not edited. There is no `uploading` document status. A document row exists only after acceptance.
- Decisions in `docs/adr/0001-direct-object-upload.md`, `docs/adr/0002-fail-closed-ingest-queue.md`, and `docs/adr/0003-immutable-accepted-originals.md` are binding. Do not add a second upload path or a second queue.
- Quota tables from `backend/alembic/versions/0005_abac_quotas.py` and outbox tables from `backend/alembic/versions/0006_ingestion_outbox.py` stay. `InMemoryQuotaService` in `backend/src/graph_rag/application/quotas/service.py` stays for unit tests and the memory backend.
- No new broker, upload service, or MCP tool.

---

## Phase 1: Setup

**Purpose**: Local test hosts for Postgres, Redis, and MinIO. No production credentials.

- [x] T001 Add Compose-backed fixtures for Postgres, Redis, and MinIO in `backend/tests/integration/conftest.py`, skipped when Docker is unavailable, using services from `docker-compose.yml`
- [x] T002 [P] Add an Azurite helper that refuses production storage account names in `backend/tests/integration/azurite_support.py`

---

## Phase 2: Foundational (Blocking)

**Purpose**: Milestone 1. Upload sessions, shared quota reservations, and a queue client that cannot silently drop a job. Blocks every user story.

**Independent of stories**: No member-facing upload yet. Existing documents and `POST /api/v1/documents/ingest` keep working.

### Tests first

- [x] T003 [P] Write a failing integration test in `backend/tests/integration/test_upload_session_migration.py` that `0013_upload_sessions` creates `upload_sessions`, leaves `documents` and `ingestion_runs` row counts unchanged, then downgrade to `0012` drops only `upload_sessions` and leaves those tables and their rows intact
- [x] T004 [P] Write a failing integration test in `backend/tests/integration/test_quota_reservations.py` that uses two separate database sessions: concurrent reserves of metric `documents` quantity `1` against a tenant limit of `1` yield one success and one `QuotaExceededError`, and the same for `storage_bytes` when the second reservation would pass the tenant ceiling. The error body names `quota`, `limit`, `used`, `remaining`, and `reset_at`. Locks target `usage_counters` on `(tenant_id, user_id, metric, period, period_key)`, tenant row before user row. A refused reserve leaves no document and no final object
- [x] T005 [P] Write a failing integration test in `backend/tests/integration/test_queue_startup.py` that process startup with `INGEST_QUEUE_BACKEND=redis` and an unreachable Redis exits before serving, and does not construct `InMemoryStreamIngestionQueue`

### Implementation

- [x] T006 Add Alembic revision `0013_upload_sessions` revising `0012_document_search` in `backend/alembic/versions/0013_upload_sessions.py` creating `upload_sessions` per `data-model.md` (`staging_object_key`, nullable `final_object_key`, `declared_byte_size` 1 through 104857600, nullable `actual_byte_size`, `etag`, `object_version_id`, `source_url`, `status` in `pending|completed|expired|rejected`, `expires_at` 15 minutes after create, nullable 64-char `content_hash`, unique `(tenant_id, staging_object_key)` and `(tenant_id, final_object_key)` where not null, unique `ingestion_run_id` where not null) and nullable `etag` plus `object_version_id` on document versions; downgrade drops `upload_sessions` and those two columns, and leaves every other document and run column in place
- [x] T007 [P] Add `UploadSessionModel` and export it from `backend/src/graph_rag/infrastructure/persistence/postgres/models/uploads.py` and `backend/src/graph_rag/infrastructure/persistence/postgres/models/__init__.py`
- [x] T008 [P] Add the domain record with those same field rules in `backend/src/graph_rag/domain/ingestion/upload_session.py`
- [x] T009 Add a tenant-scoped repository in `backend/src/graph_rag/infrastructure/persistence/postgres/repositories/upload_sessions.py` (depends on T007, T008)
- [x] T010 Implement `PostgresQuotaService` reserve, commit, and release with `SELECT … FOR UPDATE` in `backend/src/graph_rag/application/quotas/postgres.py`, taking the tenant counter lock before any user counter lock
- [x] T011 Select `PostgresQuotaService` when the metadata store is Postgres, and abort startup when required Redis cannot be opened, in `backend/src/graph_rag/application/runtime/runtime.py` and `backend/src/graph_rag/application/runtime/local.py`; keep `InMemoryQuotaService` for the memory backend. Follow `docs/adr/0002-fail-closed-ingest-queue.md`
- [x] T012 Leave `backend/src/graph_rag/domain/ingestion/stages.py` without an `uploading` status. Pending, rejected, and expired sessions live only in `upload_sessions` and create no `documents` row (`specs/001-reliable-upload-ingestion/data-model.md`)

**Checkpoint**: Foundation ready. Existing ingest still accepts a small local file through the old route.

**Verification** (local only): `cd backend && uv run alembic upgrade head && uv run pytest tests/integration/test_upload_session_migration.py tests/integration/test_quota_reservations.py tests/integration/test_queue_startup.py -m integration`

---

## Phase 3: User Story 1 - Upload a document and know it was accepted (Priority: P1) MVP

**Goal**: Milestones 2 and 3. The member sends bytes to MinIO or Azure Blob, completion validates them, and one Postgres commit writes the run and one outbox row. Abandoned and expired sessions leave no document behind.

**Independent Test**: Submit one allowed file and one rejected file. The allowed file remains after reload. The rejected file is not stored. A second complete does not create a second run.

### Tests for User Story 1

> Write these first and confirm they fail before T020–T028.

- [x] T013 [P] [US1] Add a contract test for `POST /api/v1/documents/uploads` and `POST /api/v1/documents/uploads/{upload_id}/complete` in `backend/tests/unit/test_upload_session_contract.py` against `specs/001-reliable-upload-ingestion/contracts/upload-session.schema.yaml`. The 201 body has `upload_id` and `expires_at` and no `document_id`. The 202 body has the existing `IngestAcceptedResponse` fields and no write URL
- [x] T014 [P] [US1] Add an integration test in `backend/tests/integration/test_upload_direct_minio.py` that a 100 MB object is PUT to the staging key via the write URL, the Next.js ingest route never receives those bytes (assert the route handler in `frontend/src/app/api/ingest/route.ts` is not called and the web process memory is not the store), and MinIO CORS allows that PUT from `http://localhost:3000` without a public bucket policy. Under the NFR-001 conditions the accept or reject finishes within 30 seconds
- [x] T015 [P] [US1] Add an integration test in `backend/tests/integration/test_upload_complete_idempotent.py` for a repeated complete (one run, one `ingest.queued` row), a second submission of the same bytes (409, no second active document), and a new submission of those bytes after the owner document is deleted (accepted again, one new document)
- [x] T016 [P] [US1] Add an integration test in `backend/tests/integration/test_upload_expired_and_abandoned.py` for an expired write URL and a session with no complete: status `expired` or `rejected`, both quota reservations released, staging object deleted, no final object, no document row, no outbox row
- [x] T017 [P] [US1] Add a unit test in `backend/tests/unit/test_register_source_title.py` that a non-empty title is stored and a blank title falls back to the file name
- [x] T018 [P] [US1] Add an Azurite test in `backend/tests/integration/test_azure_blob_presign_put.py` that `presign_put` writes only the reserved tenant key and a stream read hashes the object without `get_bytes` of the full file
- [x] T019 [P] [US1] Extend `frontend/src/app/upload/uploadPayload.test.ts` so the screen builds a JSON create-session body and does not append the file into multipart form data

### Implementation for User Story 1

- [x] T020 [P] [US1] Add `presign_put` for a staging key only, copy to a final key, and an async byte iterator to `backend/src/graph_rag/domain/storage/protocols.py` and `backend/src/graph_rag/infrastructure/persistence/memory/object_store.py`, rejecting keys that fail `assert_tenant_object_prefix` and expiry outside 1–900 seconds. Follow `docs/adr/0003-immutable-accepted-originals.md`
- [x] T021 [P] [US1] Implement staging `presign_put`, copy to the final key, streaming read, and retention on the final key when MinIO supports it, in `backend/src/graph_rag/infrastructure/persistence/minio/object_store.py` (depends on T020; may run beside T022)
- [x] T022 [P] [US1] Implement staging `presign_put`, copy to the final blob, streaming read, and an immutability policy when Azure Blob supports it, in `backend/src/graph_rag/infrastructure/persistence/azure_blob/object_store.py` (depends on T020; may run beside T021). Record the version id when versioning returns one
- [x] T023 [US1] Stream hash, byte-size (1 through 104857600), MIME allow-list, and archive checks in `backend/src/graph_rag/application/ingestion/verify_object.py` without holding the full object
- [x] T024 [US1] Implement create, complete, and expire in `backend/src/graph_rag/application/ingestion/upload_session.py`: no document row until the completion transaction copies staging to the final key, stores size and etag, deletes staging, then inserts document, version, stages, and one `ingest.queued` outbox row and sets status `ingesting`; a second complete returns the same ids; a size or etag mismatch refuses the object (depends on T009, T010, T020, T023; `docs/adr/0001` and `docs/adr/0003`)
- [x] T025 [US1] Prefer a non-empty request title in `backend/src/graph_rag/application/ingestion/register_source.py` (`_title_from_source`) and use the same rule from `upload_session.py`
- [x] T026 [US1] Add the two session routes in `backend/src/graph_rag/api/routes/documents.py` and request models in `backend/src/graph_rag/api/schemas/common.py`; leave `POST /ingest` and `IngestAcceptedResponse` fields unchanged and still enqueue through the outbox
- [x] T027 [US1] Sweep `pending` sessions whose `expires_at` has passed inside the existing publisher loop in `backend/src/graph_rag/api/app.py`
- [x] T028 [US1] Switch the upload screen to create, direct PUT, and complete in `frontend/src/app/upload/page.tsx`, `frontend/src/app/upload/uploadPayload.ts`, `frontend/src/app/api/documents/uploads/route.ts`, and `frontend/src/app/api/documents/uploads/[uploadId]/complete/route.ts`; stop sending file bytes through `frontend/src/app/api/ingest/route.ts`

**Checkpoint**: User Story 1 works on its own. A member can accept or reject a file without the web pod holding it. Processing may still sit until the worker is running.

**Verification** (local only): `cd backend && uv run pytest tests/unit/test_upload_session_contract.py tests/unit/test_register_source_title.py tests/integration/test_upload_direct_minio.py tests/integration/test_upload_complete_idempotent.py tests/integration/test_upload_expired_and_abandoned.py tests/integration/test_azure_blob_presign_put.py -m "unit or integration"` and `cd frontend && npm test -- uploadPayload`

---

## Phase 4: User Story 2 - Watch processing finish or fail in the open (Priority: P2)

**Goal**: Milestones 5 and 6 for the member view and the worker health signal. The screen never spins through a failed poll or a run with no heartbeat for 2 minutes. The OVH worker Deployment exposes that health.

**Independent Test**: Accept a document, stop the worker, and see stalled within 2 minutes. Separately, force the progress request to fail and see an error instead of a spinner.

### Tests for User Story 2

- [x] T029 [P] [US2] Add a unit test in `backend/tests/unit/test_ingestion_progress_state.py` that a non-terminal run with null or `heartbeat_at` older than 120 seconds yields `progress_state=stalled` and includes `last_completed_stage`, and terminal statuses map to `ready`, `partial`, `failed`, or `cancelled` per `specs/001-reliable-upload-ingestion/contracts/ingestion-progress.schema.yaml`
- [x] T030 [P] [US2] Add `frontend/src/app/upload/uploadProgress.test.ts` asserting a non-OK progress response and a `stalled` or `failed` body clear the busy spinner
- [x] T031 [P] [US2] Add a unit test in `backend/tests/unit/test_worker_health.py` that liveness is up while the process runs and readiness fails when Redis or Postgres is refused

### Implementation for User Story 2

- [x] T032 [US2] Add additive `progress_state`, `heartbeat_at`, and `last_completed_stage` on the existing run response in `backend/src/graph_rag/api/schemas/common.py` and `backend/src/graph_rag/api/routes/ingestion.py` without removing current fields
- [x] T033 [US2] Stop the spinner on poll failure and on `progress_state` `stalled` or `failed` in `frontend/src/app/upload/page.tsx` (depends on T028, T032)
- [x] T034 [US2] Serve liveness and readiness on port 8081 from the existing worker process in `backend/src/graph_rag/infrastructure/workers/main.py`, checking Postgres, Redis, and the configured object store for readiness
- [x] T035 [US2] Add HTTP probes to port 8081 in `infra/k8s/worker/deployment.yaml` while keeping `replicas: 1`, the current CPU and memory limits, and the `enterprise-rag worker` command (depends on T034)
- [x] T036 [P] [US2] Append `INGEST_EXECUTION=worker` and `INGEST_QUEUE_BACKEND=redis` in the API init container in `infra/k8s/api/deployment.yaml`, matching the worker manifest and `docker-compose.yml`

**Checkpoint**: User Stories 1 and 2 work. Status is visible without a worker code change to the stage machine.

**Verification** (local only): `cd backend && uv run pytest tests/unit/test_ingestion_progress_state.py tests/unit/test_worker_health.py` and `cd frontend && npm test -- uploadProgress`. Manifest review only for T035 and T036; do not apply them to the OVH cluster in this phase.

---

## Phase 5: User Story 3 - Recover a document without duplicating it (Priority: P3)

**Goal**: Milestone 4. Redis loss, API restart, and worker crash do not drop a committed job or create a second original.

**Independent Test**: Interrupt one run after the original is stored, restart the worker, and finish with one original and one active searchable copy. A permanent failure appears once on the failed list.

### Tests for User Story 3

- [x] T037 [P] [US3] Add `backend/tests/integration/test_worker_crash_recovery.py` that kills the worker before ack, leaves the Redis message unacked, and lets a restarted worker finish the same run without a second original
- [x] T038 [P] [US3] Add `backend/tests/integration/test_outbox_restart.py` that an API restart after the completion commit republishes an unpublished `ingest.queued` row exactly once
- [x] T039 [P] [US3] Add `backend/tests/integration/test_reprocess_single_original.py` that reprocess keeps one original object and does not insert a second active document

### Implementation for User Story 3

- [x] T040 [US3] In `backend/src/graph_rag/infrastructure/workers/ingestion_worker.py`, keep ack after durable success or after a dead-letter write. A stage already `completed` for the same tenant, version, config fingerprint, and content hash is skipped. A stage is attempted at most `RetryPolicy.max_attempts` (3). The failure that makes `should_retry` false writes one dead letter with tenant, run, stage, and a safe code, then acks, and is not retried. Refuse a final object whose size or etag no longer matches the version row. This task is required even when T037 already passes

**Checkpoint**: Recovery matches the existing stage machine. No new pipeline.

**Verification** (local only): `cd backend && uv run pytest tests/integration/test_worker_crash_recovery.py tests/integration/test_outbox_restart.py tests/integration/test_reprocess_single_original.py tests/integration/test_queue_startup.py -m integration`

---

## Phase 6: User Story 4 - Keep every document inside its organization (Priority: P4)

**Goal**: A second organization cannot read a session, a run, an error, or an object key from the first.

**Independent Test**: Upload as tenant A. As tenant B, session complete, run GET, and object read are refused and reveal no title or error text.

### Tests for User Story 4

- [x] T041 [P] [US4] Add `backend/tests/integration/test_upload_tenant_isolation.py` covering create, complete, run GET, reprocess, and the failed list for a foreign `upload_id`, a foreign document, and a foreign object key. Tenant B receives a refusal, not an empty success, and sees none of tenant A's rows

### Implementation for User Story 4

- [x] T042 [US4] Fail closed on foreign tenant ids in `backend/src/graph_rag/application/ingestion/upload_session.py` and `backend/src/graph_rag/api/routes/documents.py`, reusing `assert_tenant_object_prefix` and the existing not-found or forbidden responses

**Checkpoint**: All four stories are independently testable. Isolation holds for failures as well as successes.

**Verification** (local only): `cd backend && uv run pytest tests/integration/test_upload_tenant_isolation.py -m integration`

---

## Phase 7: Polish and Cross-Cutting

**Purpose**: Milestones 7 and 8. Observability, the full local journey, and a rollout checklist. Production deployment is not executed here.

- [x] T043 [P] Increment `upload_sessions_created_total`, `upload_sessions_completed_total`, `upload_sessions_rejected_total`, and `upload_sessions_expired_total` from `backend/src/graph_rag/application/ingestion/upload_session.py` via `backend/src/graph_rag/infrastructure/observability/metrics.py`, and keep `ingest_publish_failures_total`
- [x] T044 [P] Redact write URLs and presign query strings in `backend/src/graph_rag/shared/redaction.py`
- [x] T045 Run the local journey in `specs/001-reliable-upload-ingestion/quickstart.md` against Compose only, and record the command output in the task notes; do not use a production database, Key Vault, or object store. Passed on 2026-10-27 against local Compose only (Next on 127.0.0.1:3010, API on 127.0.0.1:8010, one worker, MinIO, Redis on 6380). Signed in as the local demo member. The browser PUT `notes.pdf` to the MinIO staging key and did not send the file to the Next.js ingest route; complete and progress followed, and the document list showed the document. An executable was rejected on screen with “Unable to detect a supported MIME type from content” and created no document. A failed progress poll showed “Status could not be loaded.” and the spinner stopped. With the worker stopped, the next file showed `pending · stalled` and the spinner stopped inside 2 minutes. Restarting the worker reclaimed the stale run; that document reached ready and the first document reached partial, each with one original. Submitting the same PDF again named the existing document. A later PUT to the staging URL left the accepted original unchanged. Session expiry has no browser control (15-minute server TTL) and stays covered by the integration suite. `pytest tests/unit`: 576 passed. `pytest tests/integration -m integration`: 31 passed, 1 deselected. `alembic upgrade head` was applied only to the local Compose `enterprise_rag` database after confirming it had no user tables and writing a schema dump to `/tmp/enterprise_rag-before-0013.sql`; head is `0013_upload_sessions`. Production was not used. The rollback downgrade was not run.
- [x] T046 [P] Write the operator checklist in `specs/001-reliable-upload-ingestion/rollout.md`: local downgrade drops only `upload_sessions` and the nullable version columns from this feature; OVH order is migration, then API and worker together, then web; Azure Blob CORS for the web origin is an operator step when that backend is selected and is not applied during implementation; production apply is out of band. State that trace export and restore drills are not implemented and are due 2027-01-31 under the constitution exceptions. Do not claim they exist
- [x] T047 Confirm existing ingest fields still match `backend/tests/unit/test_query_ingestion_contracts.py` and `docs/contracts/ingestion-result.schema.yaml` after the session routes exist
- [x] T048 [P] [US1] Add `backend/tests/integration/test_upload_rejected_types.py` for an empty object, a declared size above 104857600, and a disallowed MIME type: each returns a specific reason, leaves zero `documents` rows, no final object, and no outbox row (FR-003, SC-007)
- [x] T049 [US1] Set MinIO bucket CORS for PUT from the Compose web origin and `http://localhost:3000` in `docker-compose.yml` or the MinIO init used by Compose, without a public read or write policy (depends on T014; `docs/adr/0001`)
- [x] T050 [P] [US1] Add `backend/tests/integration/test_upload_immutable_original.py`: after complete, a PUT with the original write URL does not change the final object; a size or etag mismatch is refused by complete and by the worker; one final object remains (FR-002, SC-005)
- [x] T051 [P] [US3] Add `backend/tests/integration/test_stage_retry_and_dead_letter.py`: fail one stage, resume, earlier stages stay completed, the stage is attempted at most 3 times, and the failure that makes `should_retry` false is one dead-letter row with tenant, run, stage, and a safe code and is not retried (FR-010, FR-012)
- [x] T052 [P] [US3] Add `backend/tests/integration/test_failed_list_retry.py`: the failed list returns organization, document, step, safe reason, and time, and an authorized retry creates a new run without a new upload or a second original (FR-011, SC-008)
- [x] T053 [P] [US2] Add `backend/tests/integration/test_worker_stall_progress.py`: with the worker stopped, GET of the run returns `progress_state=stalled` and `last_completed_stage` within 120 seconds (FR-014, SC-003, NFR-006)
- [x] T054 [P] [US1] Add `backend/tests/integration/test_upload_concurrent_100mb.py`: two simultaneous 100 MB uploads by one member each reach an acceptance decision, and a following status request still succeeds, without either file body entering `frontend/src/app/api/ingest/route.ts` (NFR-001, NFR-002, SC-002)
- [x] T055 [P] [US1] Add `backend/tests/integration/test_upload_remote_url.py` using the existing safe fetcher: a private or credentialed URL is rejected with no document; an HTTPS fixture within the size and type rules completes through the same outbox transaction (FR-016)
- [x] T056 [P] Assert structured logs for session create, complete, and expire in `backend/tests/unit/test_upload_session_logs.py` include tenant id, upload id, and run id when present, and omit write URLs and file bytes. Emit those logs from `backend/src/graph_rag/application/ingestion/upload_session.py` (FR-018, FR-019)
- [x] T057 [US3] Expose organization, document, step, safe reason, and time for failed items on the existing documents or ops list in `backend/src/graph_rag/api/routes/documents.py` or `backend/src/graph_rag/api/routes/ops.py`, reading current stage and dead-letter rows. Do not add a new service. Authorized retry stays on `POST /documents/{document_id}/reprocess` (FR-011, SC-008; verified by T052)
- [x] T058 [US1] When a session carries `source_url` and no file, fetch it with `SafeUrlFetcher` in `backend/src/graph_rag/application/ingestion/upload_session.py`, apply the same size and type checks, write the final object, and commit the same outbox transaction. A blocked URL creates no document (FR-016; verified by T055)

**Verification** (local only): `cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy src && uv run pytest tests/unit && uv run pytest tests/integration -m integration` and `cd frontend && npm test -- upload`

---

## Dependencies and Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup; blocks all stories
- **US1 (Phase 3)**: depends on Foundational; no dependency on US2–US4
- **US2 (Phase 4)**: depends on Foundational; the screen task T033 depends on US1 T028
- **US3 (Phase 5)**: depends on Foundational and on a committed outbox row from US1
- **US4 (Phase 6)**: depends on US1 session routes
- **Polish**: depends on the stories being present

### Milestone map

| Milestone | Tasks |
| --- | --- |
| 1. Migration, sessions, quotas, outbox boundary | T003–T012 |
| 2. Direct upload, MinIO and Azure Blob | T014, T018, T020–T022, T028, T049, T054 |
| 3. Completion, validation, idempotency, orphan cleanup | T015, T016, T023–T027, T048, T050, T055 |
| 4. Queue, ack, recovery | T005, T011, T024, T037–T040, T051, T052 |
| 5. Frontend, progress, errors | T019, T028, T029, T030, T032, T033, T053 |
| 6. Worker health and OVH config | T031, T034–T036 |
| 7. Integration, concurrency, failure tests | T003–T005, T013–T018, T029–T031, T037–T039, T041, T047–T055 |
| 8. Observability, migration check, rollout and rollback | T043–T046, T056 |

### User story dependencies

- **US1 (P1)**: after Phase 2 only. MVP.
- **US2 (P2)**: progress derivation can start after Phase 2; the screen edit waits for T028
- **US3 (P3)**: after US1 completion commits an outbox row
- **US4 (P4)**: after US1 routes exist

### Failure scenarios

| Scenario | Where it is proved |
| --- | --- |
| Redis outage at startup | T005, T011, T040 verification |
| API restart after commit | T038 |
| Worker crash before ack | T037, T040 |
| Duplicate upload | T015 |
| Expired write URL | T016 |
| Concurrent quota use | T004, T010 |
| Abandoned upload | T016, T027 |
| Empty, oversized, or disallowed type | T048 |
| Write URL after acceptance | T050 |
| Worker stopped, progress stalls | T053 |
| Bounded retry and dead letter | T040, T051 |
| Failed list and retry without upload | T052 |
| Two simultaneous 100 MB uploads | T054 |
| Private remote URL | T055 |
| Cross-tenant reprocess and failed list | T041 |

### Parallel opportunities

- T001 and T002
- T003, T004, and T005
- T007 and T008 after the tests exist
- T013–T019 together
- T021 and T022 together after T020
- T029, T030, and T031 together
- T034 then T035; T036 in parallel with T034
- T037, T038, T039, T051, and T052 together
- T043, T044, T046, and T056 together
- T048, T050, T054, and T055 together after T024
- T021 and T022 are both [P] after T020

### Parallel example: User Story 1

```bash
# Tests together, before implementation:
backend/tests/unit/test_upload_session_contract.py
backend/tests/integration/test_upload_direct_minio.py
backend/tests/integration/test_upload_complete_idempotent.py
backend/tests/integration/test_upload_expired_and_abandoned.py
backend/tests/unit/test_register_source_title.py
backend/tests/integration/test_azure_blob_presign_put.py
frontend/src/app/upload/uploadPayload.test.ts

# Adapters together, after the protocol task is specified:
backend/src/graph_rag/infrastructure/persistence/minio/object_store.py
backend/src/graph_rag/infrastructure/persistence/azure_blob/object_store.py
backend/src/graph_rag/infrastructure/persistence/memory/object_store.py
```

---

## Implementation Strategy

### MVP first (User Story 1)

1. Finish Phase 1 and Phase 2.
2. Finish Phase 3.
3. Stop and run the US1 verification commands against Compose.
4. Do not deploy to OVH at this stop.

### Incremental delivery

1. Foundation: migration and shared quotas, old ingest still works.
2. US1: direct upload and durable accept. Deployable later as API plus web, with the worker image unchanged.
3. US2: honest progress and worker probes. Manifests stay unapplied until a reviewed release.
4. US3: failure recovery on the existing worker.
5. US4: tenant refusal tests.
6. Polish: metrics and the local quickstart. `rollout.md` is the only production document, and applying it is out of band.

### Local versus production

- Local: Compose Postgres, Redis, MinIO, and Azurite. Commands in each checkpoint.
- Production: not used for tests, migrations, or kubectl. T035, T036, and T046 describe OVH manifest and rollout steps for a later operator. They must not be applied while implementing these tasks.
- Downtime: `0013` is additive. Old API builds ignore `upload_sessions`. Roll the web image only after the API that serves the session routes is ready. Rollback the web image first. Downgrade drops `upload_sessions` and the nullable version columns from `0013` only when no row is `pending`.

---

## Notes

- [P] tasks touch different files and do not depend on an unfinished task
- Tests are written to fail before the implementation task they name
- Do not rewrite existing documents, vectors, or graph rows
- Do not add MCP tools or a second ingestion pipeline

## Requirement coverage

Every requirement below has one implementation task and one verification task. Tests are the verification tasks.

| Requirement | Implementation | Verification |
| --- | --- | --- |
| FR-001 | T026, T028 | T013, T014 |
| FR-002 | T024, T020 | T015, T050 |
| FR-003 | T023, T024 | T016, T048 |
| FR-004 | T023 | T018, T048 |
| FR-005 | T025 | T017 |
| FR-006 | T024 | T015 |
| FR-007 | T042 | T041 |
| FR-008 | T024, T011 | T038 |
| FR-009 | T024 | T029, T032 |
| FR-010 | T040 | T051 |
| FR-011 | T057 | T052 |
| FR-012 | T040 | T051, T039 |
| FR-013 | T032, T033 | T029, T030 |
| FR-014 | T032 | T029, T053 |
| FR-015 | T010 | T004 |
| FR-016 | T058 | T055 |
| FR-017 | existing reprocess route, T040 | T039 |
| FR-018 | T044, T056 | T056 |
| FR-019 | T008, T024 | T013, T056 |
| FR-020 | T026, T047 | T047 |
| NFR-001 | T028, T049 | T014, T054 |
| NFR-002 | T028, T049 | T054 |
| NFR-003 | T024, T011 | T038 |
| NFR-004 | T040 | T037, T039 |
| NFR-005 | T042 | T041 |
| NFR-006 | T034, T035 | T031, T053 |
| NFR-007 | T045 | T002, T045 |
| SC-001 | T028 | T014, T045 |
| SC-002 | T028 | T014, T054 |
| SC-003 | T032, T033 | T030, T053 |
| SC-004 | T024 | T015 |
| SC-005 | T040, T024 | T037, T050 |
| SC-006 | T042 | T041 |
| SC-007 | T023 | T048 |
| SC-008 | T057 | T052 |
| SC-009 | T045 | T014, T015, T016, T041, T048, T053, T037 |

# Quickstart: Reliable Document Upload and Ingestion

Validation only. Do not point these commands at production, and do not apply the migration to a production database as part of this plan.

## Prerequisites

- Docker Compose from the repository root, with Postgres, Redis, and MinIO healthy.
- Backend dependencies installed with `uv` in `backend/`.
- A non-production `.env` copied from `.env.example`. Leave production secret stores alone.
- `OBJECT_STORE_BACKEND=minio` for the default journey. The Azure Blob adapter is validated separately against Azurite, not against the production account.

## Setup

```bash
cp .env.example .env
docker compose up -d --wait postgres redis minio
cd backend
uv sync --all-extras
uv run alembic upgrade head
```

Confirm the new revision is `0013_upload_sessions` and that existing rows in `documents` and `ingestion_runs` are unchanged.

## Automated checks

From `backend/`:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest tests/unit
uv run pytest tests/integration -m integration
```

The integration module must start Postgres, Redis, and MinIO. Required cases:

- One 100 MB object, with no other upload running, is accepted or rejected within 30 seconds. The write URL targets the staging key. The Next.js ingest route does not receive the body.
- Two simultaneous 100 MB uploads each reach a decision, and a following status request still succeeds.
- MinIO CORS allows the browser PUT from `http://localhost:3000`. The bucket is not public.
- Completing the same session twice returns one run and one outbox row.
- An identical second file returns a conflict and no second document. After that document is deleted, the same bytes may be submitted again.
- Empty, oversized, and disallowed-type submissions leave no document row.
- A later PUT with the write URL does not change the final object.
- A cross-tenant read, reprocess, or failed-list request is refused.
- Two database sessions reserving `documents` or `storage_bytes` past the tenant ceiling yield one success and one 429 that names quota, limit, used, remaining, and reset_at.
- Stopping the worker before ack leaves the Redis message unacked; a restarted worker finishes the same run, skips completed stages, and does not write a second original.
- A stage is attempted at most 3 times. The failure that exhausts that bound is one dead letter and is not retried.
- The failed list shows organization, document, step, reason, and time. Retry does not upload the file again.
- With the worker stopped, run status is `stalled` and names the last completed step within 120 seconds.
- The API process exits on startup when `INGEST_QUEUE_BACKEND=redis` and Redis cannot be opened. It must not serve a 202 from an in-memory queue.
- An expired session releases both quota reservations, deletes the staging object, and leaves no document.
- A private remote URL is rejected with no document. A public HTTPS fixture uses the same acceptance transaction.
- `alembic downgrade 0012_document_search` drops only `upload_sessions` and the nullable version columns from `0013`. Document and run rows remain.

Frontend, from `frontend/`:

```bash
npm test -- upload
```

The upload page test must show a visible error, and must not leave the spinner running, when the progress request fails.

## Manual local journey

1. Start the API with `INGEST_EXECUTION=worker` and `INGEST_QUEUE_BACKEND=redis`, and start one worker with the same values.
2. Sign in as a member of a local tenant.
3. Submit a small PDF from the upload screen. Confirm the browser sends the file to MinIO, not to the Next.js ingest route.
4. Reload the document list. The document is still present.
5. Watch the screen until the run is ready, or until a failed step shows a reason.
6. Stop the worker and submit another file. Within 2 minutes the screen shows stalled, not a spinner.
7. Start the worker. The same document reaches a terminal state and still has one original.
8. Submit the same PDF again. The screen names the existing document.

Expected: no step above requires reading a production database or a production object store.

## Rollback drill (local)

1. Point the web app back at the multipart ingest route.
2. Run `uv run alembic downgrade 0012_document_search`.
3. Submit a small file through the old route and confirm one run is queued to Redis.

The downgrade drops `upload_sessions` and the nullable `etag` and `object_version_id` columns from revision `0013`. Documents, runs, and quota tables from earlier revisions remain. Trace export and restore drills are not part of this journey. Those controls are not implemented. Their recorded deadline is 2027-01-31.

# Rollout: reliable upload and ingestion

This checklist is for a later operator. Do not apply it while implementing, and do not point it at production from a development session.

## Not implemented

Trace export and restore drills are not implemented. The constitution records both as exceptions owned by the Enterprise RAG team, due 2027-01-31. Azure Blob soft-delete is not a restore drill. Do not describe those controls as present.

## Local downgrade

`alembic downgrade 0012_document_search` drops `upload_sessions` and the nullable `etag` and `object_version_id` columns added by `0013`. Other document and run columns stay. Wait until no upload session is `pending`.

## OVH order

1. Confirm Redis is reachable.
2. Apply migration `0013_upload_sessions` with the existing migration job.
3. Deploy the API and worker images together. The API manifest sets `INGEST_EXECUTION=worker` and `INGEST_QUEUE_BACKEND=redis`. The worker manifest probes port 8081. Replicas stay 1 on the worker.
4. Deploy the web image that uses the session flow.
5. When `OBJECT_STORE_BACKEND=azure_blob`, set Azure Blob CORS for the web origin before members use the screen. That step is not applied by implementation. Local MinIO CORS is configured in Compose for `http://localhost:3000`.

## Rollback

1. Deploy the previous web image so the screen uses multipart ingest again.
2. Deploy the previous API and worker images if fail-closed queue startup is the problem.
3. Leave revision `0013` in place unless a downgrade is required.

Do not delete documents, runs, or objects to roll back.

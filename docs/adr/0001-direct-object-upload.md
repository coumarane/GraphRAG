# ADR 0001: Direct upload to the existing object store

**Status**: Accepted for feature `001-reliable-upload-ingestion`  
**Date**: 2026-10-27

## Context

The upload screen reads the whole file and forwards a second copy. The web process is limited to 512 MB, and the product allows a 100 MB file. Constitution Principle II, as amended in version 2.0.0, allows one short-lived write URL to the member who started the upload, for a staging key only.

## Decision

The browser requests a session with JSON, then PUTs the bytes to a staging object using a write URL that expires within 15 minutes. The web process does not carry the file. The API streams the staging object on completion. MinIO is the target when `OBJECT_STORE_BACKEND=minio`. Azure Blob is the target when it is `azure_blob`. The cluster that runs the API remains the OVH Kubernetes cluster.

The existing `POST /api/v1/documents/ingest` route stays for the CLI and for remote URL intake. It does not become a second pipeline.

## Consequences

- Browser PUT requires CORS on the object store for the web origin. Local MinIO is configured in Compose. Azure Blob CORS is an operator step and is not applied by this ADR.
- Logs, traces, and errors omit the write URL.
- A document row is created only after size, type, and archive checks succeed.

## Evidence

- `frontend/src/app/api/ingest/route.ts` buffers the body today.
- `infra/k8s/web/deployment.yaml` sets a 512Mi memory limit.
- `ObjectStore.presign_get` already exists on the MinIO and Azure Blob adapters.

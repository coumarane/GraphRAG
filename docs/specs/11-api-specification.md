# 11 — API Specification

Base path: `/api/v1`.

## Documents

### `POST /documents/ingest`

Accept multipart upload or a safe remote URL request. Return `202 Accepted` with ingestion-run ID.

### `GET /documents/{document_id}`

Return document metadata and current version state.

### `GET /documents/{document_id}/elements`

Filter by version, page, modality and element type. Paginated.

### `GET /documents/{document_id}/graph`

Return bounded structural or semantic graph view.

### `DELETE /documents/{document_id}`

Submit asynchronous deletion and return operation ID.

## Ingestion

### `GET /ingestion-runs/{run_id}`

Return state, stage progress, warnings and errors.

### `POST /ingestion-runs/{run_id}/resume`

Resume an eligible failed or partial run.

### `POST /ingestion-runs/{run_id}/cancel`

Request cancellation.

## Retrieval and query

### `POST /retrieval/search`

Return evidence without answer generation.

### `POST /query`

Request fields:

- question;
- tenant resolved from authenticated context;
- mode;
- document filters;
- modality filters;
- tags and security labels;
- top-k;
- graph depth;
- include graph paths;
- answer model override when authorized.

### `POST /graph/search`

Execute controlled graph search using typed request fields, not arbitrary Cypher.

## Assets

### `GET /assets/{asset_id}`

Return authorized presigned URL or stream. Never reveal unrestricted MinIO credentials.

## Operations

- `GET /health/live`
- `GET /health/ready`
- `GET /metrics`

## Error format

Use RFC 9457-style problem details with:

- type;
- title;
- status;
- detail;
- instance;
- error code;
- correlation ID;
- safe metadata.

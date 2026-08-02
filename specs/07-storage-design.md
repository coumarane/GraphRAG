# 07 — Storage Design

## PostgreSQL ownership

System of record for:

- tenants;
- documents and versions;
- ingestion runs and stages;
- parser attempts;
- pages and normalized elements;
- sections and assets;
- parent and child chunks;
- extraction outputs;
- entity mentions and resolution decisions;
- model usage;
- retrieval and answer audit;
- deletion and retention state.

Use async SQLAlchemy 2 and Alembic. Use JSONB only for variable metadata.

## MinIO ownership

Store immutable or versioned blobs:

```text
tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/original/{safe_filename}
tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/pages/{page}.png
tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/assets/{asset_id}.{ext}
tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/normalized/document.json
tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/derived/document.md
```

Never use a raw client filename as an object key component without sanitization.

## Qdrant ownership

Initial collections:

- `rag_chunks` with named vectors `content` and optional `summary`;
- `rag_entities`;
- `rag_communities`.

Chunk payload fields:

- tenant ID;
- document and version IDs;
- chunk and parent IDs;
- modality and element type;
- page range;
- section path;
- language;
- parser;
- content hash;
- security labels;
- source object keys.

Create payload indexes for tenant, document, modality, tags and security filters.

## Neo4j ownership

Store:

- structural document graph;
- semantic entity graph;
- claims and measurements;
- cross-document relations;
- provenance links;
- optional graph communities.

Every node and relationship must contain `tenant_id` or be reachable only through a tenant-specific database strategy. Default is mandatory `tenant_id` properties.

## Redis ownership

Use only for ephemeral concerns:

- queues;
- distributed locks;
- progress events;
- capacity coordination;
- short-lived retrieval cache;
- idempotency lock windows.

Redis is not the source of truth for ingestion status.

## Consistency model

PostgreSQL owns lifecycle state. External indexes are derived projections. Use outbox-like stage records or explicit projection states so failed Qdrant/Neo4j updates can be retried.

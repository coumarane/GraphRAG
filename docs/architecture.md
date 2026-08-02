# Architecture

Enterprise RAG-Anything separates parsing, enrichment, indexing and query into explicit adapters over PostgreSQL, MinIO, Qdrant, Neo4j and Redis.

```mermaid
flowchart LR
  CLI[CLI / API] --> App[Application services]
  App --> PG[(PostgreSQL lifecycle)]
  App --> MinIO[(MinIO objects)]
  App --> Qdrant[(Qdrant vectors)]
  App --> Neo4j[(Neo4j graph)]
  App --> Redis[(Redis queue/cache)]
  Worker[Ingestion worker] --> App
```

## Ingestion sequence

```mermaid
sequenceDiagram
  participant C as Client
  participant API as API
  participant W as Worker
  participant S as Stores
  C->>API: ingest document
  API->>S: register version + object
  API->>W: enqueue run
  W->>S: parse / enrich / chunk / embed / graph
  W-->>API: stage progress
  C->>API: query
  API->>S: retrieve + generate grounded answer
```

## Boundaries

- Domain protocols never import provider SDKs.
- Tenant context is required on every store operation.
- Document content is untrusted data inside prompt trust boundaries.
- Shared graph entities are deleted only when orphaned.

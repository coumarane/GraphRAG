# 02 — System Architecture

## Architectural style

Use clean architecture with ports and adapters.

```text
API / CLI / Worker
        |
Application use cases and orchestration
        |
Domain models, policies and provider protocols
        ^
Infrastructure adapters
```

## Components

### API service

Responsibilities:

- authentication and tenant-context resolution;
- request validation;
- ingestion submission;
- query execution;
- document, asset and run status endpoints;
- readiness, liveness and metrics.

The API must not execute long parsing jobs inline.

### Worker service

Responsibilities:

- claim ingestion tasks;
- execute resumable stages;
- emit progress;
- apply retries and dead-letter rules;
- enforce global, parser, model and tenant concurrency limits.

### Application layer

Use cases:

- register document;
- ingest document;
- resume ingestion;
- delete document;
- rebuild vectors;
- rebuild graph;
- execute retrieval;
- generate grounded answer;
- inspect document and graph.

### Domain layer

Contains:

- normalized document and element types;
- ingestion state machine;
- chunk and citation models;
- graph vocabulary;
- retrieval request/result types;
- repository and provider protocols;
- tenant and authorization policies.

### Infrastructure layer

Adapters for:

- PostgreSQL;
- MinIO;
- Qdrant;
- Neo4j;
- Redis;
- MinerU;
- Docling;
- Marker;
- PaddleOCR;
- pypdfium2;
- LangChain OpenAI;
- direct OpenAI SDK;
- telemetry.

## Concurrency architecture

After normalization, independent branches may run concurrently:

```text
Normalized document
  |-- text and hierarchy chunking
  |-- image/chart enrichment
  |-- table enrichment
  |-- equation enrichment
```

Graph extraction must wait for required enriched elements. Vector indexing may start in batches after chunks are finalized.

Use semaphores or capacity limiters for:

- per-parser execution;
- OCR pages;
- vision calls;
- text LLM calls;
- embeddings;
- storage writes.

## Failure boundaries

- Parser adapters return typed failures.
- Application orchestration decides fallback.
- Storage failures do not get mistaken for parser failures.
- Partial completion is explicit.
- `FINALIZE` executes only after required stages meet policy.

## Extensibility

Adding a parser, model provider, vector store or task executor must require a new adapter and configuration, not changes to domain models or core orchestration.

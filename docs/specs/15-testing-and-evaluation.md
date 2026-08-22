# 15 — Testing and Evaluation

## Unit tests

Cover:

- parser inspection and routing;
- fallback policy;
- parser normalization;
- deterministic IDs and hashes;
- context-window construction;
- table and equation preservation;
- parent/child/composite chunking;
- graph vocabulary validation;
- entity resolution scoring;
- query classification;
- retrieval score fusion;
- tenant filter enforcement;
- citation validation;
- CLI precedence and validation.

## Integration tests

Use containers for PostgreSQL, MinIO, Qdrant, Neo4j and Redis.

Scenarios:

- complete mixed-document ingestion;
- scanned PDF;
- parser failure and fallback;
- duplicate version;
- resume after vector-index failure;
- graph rebuild;
- vector rebuild;
- asset retrieval;
- document deletion;
- cross-document entity relation;
- cross-tenant rejection.

## Contract tests

Every parser adapter must pass the normalized-document contract. Every model adapter must pass generation, extraction and embedding protocol tests.

## Evaluation corpus

Include a small versioned corpus containing:

- a text-heavy PDF;
- a scanned PDF;
- a scientific PDF with equations;
- a document with charts;
- a document with complex tables;
- two documents sharing entities and conflicting measurements.

## Metrics

- retrieval hit rate;
- context precision and recall;
- multimodal retrieval accuracy;
- graph-path accuracy;
- entity-resolution precision;
- citation precision;
- answer groundedness;
- unsupported-claim rate;
- latency and cost per query/document.

Live model tests require `RUN_LIVE_OPENAI_TESTS=true`.

# 14 — Observability

## Structured logs

Required fields where applicable:

- timestamp;
- level;
- service;
- environment;
- correlation ID;
- trace ID;
- tenant ID;
- document ID and version;
- ingestion-run ID;
- stage;
- parser and model;
- page or element ID;
- duration;
- retry count;
- result status;
- safe error code.

## Metrics

Counters:

- documents submitted/completed/failed;
- pages parsed;
- parser attempts and fallbacks;
- OCR pages;
- images/tables/equations processed;
- model requests and failures;
- vectors indexed;
- graph nodes and relations indexed;
- citation validation failures.

Histograms:

- stage duration;
- parser duration;
- OCR duration;
- model latency;
- embedding latency;
- Qdrant latency;
- Neo4j latency;
- retrieval and answer latency.

Gauges:

- queue depth;
- active parser jobs;
- active model requests;
- failed projection backlog.

## Tracing

Trace API/CLI submission through worker stages, model calls and storage adapters. Do not attach full sensitive document content to spans.

## Audit

Persist model usage, retrieval decisions and final citation mappings in PostgreSQL with retention controls.

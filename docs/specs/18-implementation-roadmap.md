# 18 — Implementation Roadmap

Cursor must implement in these phases.

## Phase 1 — Repository foundation

Create project tree, `pyproject.toml`, settings, logging, exception hierarchy and basic tests.

Acceptance:

```bash
uv sync
uv run ruff check .
uv run mypy src
uv run pytest tests/unit
```

## Phase 2 — Domain contracts

Implement tenant context, normalized document, elements, chunks, citations, graph vocabulary and provider protocols. Match files under `contracts/`.

## Phase 3 — PostgreSQL lifecycle persistence

Implement models, migrations, repositories, row-level security scaffolding and ingestion state machine.

## Phase 4 — MinIO and source intake

Implement local upload, safe URL fetch, MIME validation, hashing, object naming and source registration.

## Phase 5 — Parser inspection and adapters

Implement PDFium inspection, parser interface, Docling adapter, then MinerU, Marker and PaddleOCR. Add normalized conversion contract tests.

## Phase 6 — Multimodal enrichment

Implement context builder and image/chart/table/equation processors with mocked model adapters.

## Phase 7 — Chunking and embeddings

Implement hierarchical multimodal chunks, embedding protocol, LangChain/OpenAI adapters and Qdrant repository.

## Phase 8 — Knowledge graph

Implement extraction schemas, entity resolution, structural graph and semantic Neo4j projection.

## Phase 9 — Ingestion orchestration and worker

Implement resumable stages, task execution, retries, progress and dead-letter behavior.

## Phase 10 — Retrieval

Implement all retrieval modes, fusion, parent/neighbor expansion and evidence assembly.

## Phase 11 — Grounded generation

Implement answer generation, citation registry, citation validation and graph-path output.

## Phase 12 — API and CLI

Implement all specified endpoints and Typer commands including `scripts/upload_document.py` and `scripts/query_documents.py`.

## Phase 13 — Deletion and reindexing

Implement safe derived-index cleanup and shared-entity orphan rules.

## Phase 14 — Observability and security hardening

Add telemetry, metrics, redaction, resource limits and security integration tests.

## Phase 15 — Deployment and evaluation

Complete Docker Compose, images, documentation and evaluation corpus/harness.

## Final acceptance

```bash
uv sync --all-extras
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest

docker compose config
docker compose up -d --wait
uv run graph-rag ingest ../data/examples/sample.pdf --tenant-id demo --wait
uv run graph-rag query "Summarize the document" --tenant-id demo --mode auto --output json
```

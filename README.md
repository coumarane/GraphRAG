# Enterprise RAG-Anything

Production-oriented multi-tenant multimodal GraphRAG platform. Documents are parsed into a normalized multimodal model, enriched, chunked, embedded into Qdrant, projected into Neo4j, and queried with grounded citations.

## Quick start (local, in-memory)

```bash
uv sync --all-extras
cp .env.example .env
uv run ruff check .
uv run mypy src
uv run pytest tests/unit

# API (in-memory object store by default)
uv run uvicorn enterprise_rag.api.app:get_app --factory --reload

# Persist uploads to MinIO locally (requires MinIO running)
# OBJECT_STORE_BACKEND=minio uv run uvicorn enterprise_rag.api.app:get_app --factory --reload

# CLI against local container
uv run enterprise-rag ingest examples/sample.pdf --tenant-id demo --wait --output json
uv run enterprise-rag query "Summarize the document" --tenant-id demo --mode auto --output json

# Web UI (proxies to the API; http://localhost:3000)
cd frontend && npm install && npm run dev
```

## Docker Compose

Starts PostgreSQL, Redis, MinIO, Qdrant, Neo4j, API, worker, frontend, and a one-shot migration job. Compose sets `OBJECT_STORE_BACKEND=minio`, `VECTOR_STORE_BACKEND=qdrant`, and `GRAPH_STORE_BACKEND=neo4j`. For a local `uvicorn` process, set the same vars in `.env` (requires those containers healthy and enough Docker disk).

For the OVH Kubernetes cluster, production can use Azure Blob Storage instead of MinIO by setting `OBJECT_STORE_BACKEND=azure_blob` and providing the `AZURE_BLOB_*` variables in `.env.production` / Azure Key Vault.

```bash
cp .env.example .env
docker compose config
docker compose up -d --wait
# UI: http://localhost:3000  · API docs: http://localhost:8000/docs
uv run enterprise-rag ingest examples/sample.pdf --tenant-id demo --wait
uv run enterprise-rag query "Summarize the document" --tenant-id demo --mode auto --output json
```

Optional GPU worker profile (does not change the default CPU stack):

```bash
docker compose --profile gpu up -d worker-gpu
```

## Layout

| Path | Role |
|---|---|
| `src/enterprise_rag/` | Application, domain, infrastructure |
| `frontend/` | Next.js upload / query / graph UI |
| `config/` | Default / development / production YAML |
| `alembic/` | PostgreSQL migrations |
| `evaluation/` | Versioned corpus + question set |
| `examples/sample.pdf` | Smoke-test document |
| `docs/` | Architecture, evaluation, troubleshooting |
| `specs/` | Authoritative product/engineering specs |
| `contracts/` | Stable interface contracts |

## Evaluation

```bash
uv run pytest tests/evaluation -m evaluation
```

See [docs/evaluation.md](docs/evaluation.md).

## Spec-driven implementation

Authoritative guidance lives in `CURSOR.md` and `specs/18-implementation-roadmap.md`. Prefer `contracts/` over narrative specs when they diverge.

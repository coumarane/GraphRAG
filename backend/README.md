# Enterprise RAG-Anything — Backend

Python backend for the GraphRAG platform: FastAPI API, ingestion worker, CLI, and PostgreSQL migrations. Documents are parsed into a normalized multimodal model, enriched, chunked, embedded into Qdrant, projected into Neo4j, and queried with grounded citations.

Run all commands below from this `backend/` directory (or use the repo-root `Makefile`).

```bash
uv sync --all-extras
uv run ruff check .
uv run mypy src
uv run pytest tests/unit

# API (in-memory object store by default)
uv run uvicorn graph_rag.api.app:get_app --factory --reload

# CLI
uv run graph-rag ingest ../data/examples/sample.pdf --tenant-id demo --wait --output json
uv run graph-rag query "Summarize the document" --tenant-id demo --mode auto --output json
```

Container images are built from `docker/` with this directory as the build context. See the repo root [README](../README.md) for the full-stack Docker Compose setup and repository layout.

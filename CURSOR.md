# Cursor Master Instruction: Enterprise RAG-Anything

You are implementing a production-grade, multi-tenant multimodal GraphRAG platform inspired by the architecture and capabilities of RAG-Anything.

Read every file under `specs/` and `contracts/` before changing code. In case of conflict, the following precedence applies:

1. `contracts/`
2. `specs/13-security-and-multitenancy.md`
3. `specs/03-domain-and-data-model.md`
4. Other numbered specifications
5. This file

## Product objective

Build `enterprise-rag-anything`, a multimodal retrieval system that understands text, images, charts, diagrams, tables, equations, captions, headings and document layout as connected evidence.

The solution must:

- ingest local files and safe remote URLs;
- store originals and extracted assets in MinIO;
- parse using MinerU, Docling, Marker, PaddleOCR and pypdfium2 adapters;
- normalize every parser output into one application-owned document model;
- enrich visual and structured elements using configurable OpenAI text and vision models;
- store application metadata and ingestion state in PostgreSQL;
- store vectors and searchable payloads in Qdrant;
- store structural and semantic graphs in Neo4j;
- use Redis for queueing, locks, rate coordination and ephemeral progress;
- expose FastAPI endpoints and Typer commands;
- support vector, local graph, global graph, hybrid, multimodal, mix and automatic retrieval;
- return validated source citations for every answer;
- enforce tenant isolation in every storage operation.

## RAG-Anything alignment

Reproduce these architectural concepts, not source code:

- multimodal document parsing;
- dedicated text and multimodal processing pipelines;
- context-aware processing of images, tables and equations;
- knowledge-graph construction from all modalities;
- local, global, hybrid and multimodal retrieval;
- provenance between generated descriptions and source elements.

Do not copy RAG-Anything implementation code. Do not make LightRAG a required runtime component.

## LangChain policy

Use current LangChain APIs only where they reduce integration effort:

- `langchain-openai` model and embedding adapters;
- structured output binding;
- prompt composition;
- retriever interoperability;
- LangGraph only for explicit conditional workflows that benefit from persisted state.

Do not expose LangChain types in the domain layer. Do not use legacy chains, legacy retrievers, deprecated memory APIs or `langchain-classic` unless a specification explicitly authorizes it.

All model functionality must implement application-owned protocols. A direct OpenAI SDK adapter must coexist with the LangChain adapter.

## Mandatory engineering rules

- Use the newest Python release supported by the complete dependency graph; prefer Python 3.13 when OCR/parser compatibility prevents Python 3.14.
- Use `uv`, `pyproject.toml`, Pydantic v2, SQLAlchemy 2 async and Alembic.
- Use strict type annotations.
- Use async network and database I/O.
- No bare `except` blocks.
- No silent failures.
- No unbounded concurrency.
- No global mutable service clients.
- No provider SDK imports in domain modules.
- No tenant-agnostic repository methods for tenant-owned data.
- No dynamically constructed Cypher labels or predicates from raw LLM output.
- No citations that were not part of retrieved evidence.
- No placeholder `pass`, incomplete production paths or TODO-only implementations.

## Required repository structure

```text
src/enterprise_rag/
  api/
  application/
  domain/
  infrastructure/
  cli/
  config/
  shared/
scripts/
tests/unit/
tests/integration/
tests/evaluation/
alembic/
docs/
```

## Implementation workflow

Follow `specs/18-implementation-roadmap.md` exactly. For each phase:

1. State the phase goal.
2. List files to create or modify.
3. Implement complete code.
4. Add or update tests.
5. Run the phase acceptance commands.
6. Fix failures before proceeding.
7. Report design decisions and remaining risks.

Do not attempt the complete platform in one uncontrolled edit.

## Required validation commands

```bash
uv sync --all-extras
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest tests/unit
uv run pytest tests/integration
```

Integration tests may use Docker Compose or Testcontainers. OpenAI calls must be mocked unless `RUN_LIVE_OPENAI_TESTS=true`.

## Initial response required from Cursor

Before creating code, provide:

1. final repository tree;
2. Python compatibility decision;
3. package dependency groups;
4. component and storage ownership matrix;
5. parser-routing matrix;
6. ingestion state machine;
7. normalized multimodal document model summary;
8. Neo4j graph schema summary;
9. retrieval pipeline summary;
10. implementation phases and acceptance tests.

Then begin Phase 1 immediately.

# Dependency Compatibility

## Python version

**Decision:** Python **3.13** (`requires-python = ">=3.13,<3.14"`).

### Rationale

- Specs require the newest Python release supported by the complete dependency graph.
- Prefer 3.13 when OCR/parser native stacks (MinerU, PaddleOCR/PaddlePaddle, Docling, Marker) do not reliably support Python 3.14.
- Host environments may ship Python 3.14; the project pins 3.13 via `.python-version` and `uv`.

### Verification

```bash
uv python install 3.13
uv sync
uv run python -c "import sys; assert sys.version_info[:2] == (3, 13)"
```

Re-evaluate Python 3.14 only after MinerU, PaddleOCR, Docling and Marker publish verified wheels for that interpreter.

### UUIDv7 note

``uuid.uuid7`` landed in the Python standard library in **3.14**. On Python 3.13 the domain helper ``enterprise_rag.domain.ids.new_id`` uses an RFC 9562-compatible implementation and automatically prefers the stdlib function when available.

## Package layout

| Distribution name | Import package |
|---|---|
| `enterprise-rag-anything` | `enterprise_rag` |

## Dependency groups

| Group | Role |
|---|---|
| core (`project.dependencies`) | Pydantic v2, settings, structlog, PyYAML |
| `dependency-groups.dev` | Ruff, mypy, pytest, pytest-asyncio |
| `optional-dependencies.api` | FastAPI / Uvicorn |
| `optional-dependencies.cli` | Typer / Rich |
| `optional-dependencies.postgres` | SQLAlchemy async, asyncpg, Alembic |
| `optional-dependencies.redis` | Redis client |
| `optional-dependencies.minio` | MinIO SDK |
| `optional-dependencies.qdrant` | Qdrant client |
| `optional-dependencies.neo4j` | Neo4j driver |
| `optional-dependencies.llm` | OpenAI SDK + LangChain OpenAI |
| `optional-dependencies.parsers` | pypdfium2 + MIME helpers (heavy parsers added per adapter phase) |
| `optional-dependencies.observability` | OpenTelemetry + Prometheus |

Phase 1 installs core + dev only (`uv sync`). Later phases enable extras with `uv sync --extra …` or `--all-extras`.

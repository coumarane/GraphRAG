# Parsing Observability Deliverable

Implemented from `CURSOR_OBSERVABILITY.md` (2026-08-10).

## Architecture changes

- Added a **parser-independent** audit domain (`domain/parsing/audit.py`) with document / page / element / stage / routing / issue / content-loss models.
- Added **`ParsingAuditCollector`** — in-memory event collection during ingest, **one batch persist** at completion (no per-element DB transactions).
- Wired collector into **`ProcessRegisteredDocumentService`** (the live local ingest path).
- Added **compare service** for two immutable runs of the same `document_id`.
- Exposed tenant-scoped report APIs under `/api/v1/documents/...`.

## Database schema / migration

- Alembic: `alembic/versions/0002_parsing_audit.py`
- Tables (all tenant-owned + RLS on Postgres):
  - `document_parse_reports` (unique per `tenant_id` + `ingestion_run_id`)
  - `page_parse_reports`
  - `element_parse_reports`
  - `processing_stage_runs`
  - `parser_routing_decisions`
  - `ingestion_parse_issues`
  - `content_loss_records`
- Reuses existing `ingestion_runs` / `documents` / `document_versions` FKs. Runs are **insert-only** (never overwrite).

## Key modules

| Concern | Path |
| --- | --- |
| Domain models | `src/enterprise_rag/domain/parsing/audit.py` |
| Repository port | `src/enterprise_rag/domain/parsing/audit_protocols.py` |
| Collector | `src/enterprise_rag/application/ingestion/parsing_audit_collector.py` |
| Compare | `src/enterprise_rag/application/ingestion/compare_parse_reports.py` |
| Memory repo | `src/enterprise_rag/infrastructure/persistence/memory/parsing_audit.py` |
| Postgres ORM | `src/enterprise_rag/infrastructure/persistence/postgres/models/parsing_audit.py` |
| Postgres repo | `src/enterprise_rag/infrastructure/persistence/postgres/repositories/parsing_audit.py` |
| Pipeline wiring | `src/enterprise_rag/application/ingestion/local_pipeline.py` |
| API | `src/enterprise_rag/api/routes/parsing_audit.py` |

## APIs

- `GET /api/v1/documents/{document_id}/ingestion-runs`
- `GET /api/v1/documents/{document_id}/ingestion-runs/{run_id}/report`
- `GET .../pages`, `.../pages/{page_number}`, `.../elements`, `.../errors`, `.../warnings`, `.../pipeline`
- `GET /api/v1/documents/{document_id}/compare?run_a=...&run_b=...`

## Examples

- `reports/parsing-audit-example.json`
- `reports/parsing-audit-comparison-example.json`

## Tests

- `tests/unit/test_parsing_audit.py` — collector, content loss, immutable memory store, comparison
- Local pipeline test still passes with audit persistence enabled

## Critical invariant

Detected elements that do not reach normalization are recorded as **content losses** (`UNKNOWN_LOSS` unless an explicit skip/fail reason was set). Silent drop is rejected by `reconcile_content_loss()`.

## Remaining limitations

- Stage orchestrator / worker path still mostly no-op; audit is on the **local pipeline** that production API/CLI actually runs.
- Per-page OCR engine attribution is coarse (from `RawPage.is_scanned`), not every OCR call site yet.
- Vision enrichment records page-level tool usage; token usage is null unless the chat adapter exposes it.
- Confidence scores are only stored when parsers provide them (never fabricated).
- Element matching raw→normalized is best-effort by `(page, type)` order.
- Full matrix of scanned/OCR/fallback integration tests beyond unit collector/compare is still incremental.
- Apply migration with `alembic upgrade head` before using Postgres audit persistence.

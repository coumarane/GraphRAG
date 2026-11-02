# Implementation Plan: RAG Reliability and Retrieval Quality

**Branch**: `cursor/002-rag-reliability-and-retrieval-quality-7784` | **Date**: 2026-11-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-rag-reliability-and-retrieval-quality/spec.md`

## Summary

Keep Feature 001's upload session, object write, completion, and parser child. Make the worker answer liveness while a parse holds the ingestion lock. Stop rewriting a multipage parent citation onto its first page. Apply the existing 0.12 retrieval-score floor to search and to answers, and treat a missing distinctive phrase as no evidence. Return a structural graph path or an explicit reason after graph indexing. Ignore optional skip reasons when deriving run status and the latest warning. Add a DEV browser journey that uses a generated PDF, and make serving digests, rollback digests, and the acceptance job result agree.

This plan does not build an image, change a kustomization digest, or dispatch a promotion.

## Technical Context

**Language/Version**: Python 3.13 (`graph-rag`, `requires-python >=3.13,<3.14`); Next.js frontend already in `frontend/`

**Primary Dependencies**: FastAPI, the existing Redis Streams ingestion worker, Qdrant, Neo4j, Pydantic v2, Playwright

**Storage**: PostgreSQL for runs and stages, Qdrant for passage vectors, Neo4j for the graph already written by `INDEX_GRAPH`. No new Alembic revision.

**Testing**: pytest unit tests; the existing evaluation corpus where a score change is measured; Playwright for the browser journey; a local check that workflow heredocs match and that serving and rollback digests are distinct

**Target Platform**: OVH Kubernetes for a later reviewed deploy. Local tests and the existing feature-validation workflow before that. Not a new cluster and not Azure Kubernetes.

**Project Type**: Existing web application (`backend/` + `frontend/` + `infra/k8s/` + `.github/workflows/`)

**Performance Goals**: Liveness responds within 5 seconds during a parse. Page citations on the four-page fixture match the page that contains the sentence. An unsupported pinned question returns no evidence.

**Constraints**: Do not replace the upload architecture. Do not add Celery. Do not change PDFium, Torch, or Marker versions. Do not enable community summarization to clear a warning. Do not open the release-gate promotion switches. Do not print secrets. Repository dispatch executes workflow YAML from the default branch.

**Scale/Scope**: The current one worker replica and two API replicas. Worker replica count stays 1.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Result |
| --- | --- | --- |
| I. Clean architecture and compatible interfaces | Liveness stays in the worker entrypoint. Citation page rules stay in the citation domain. The evidence floor stays in retrieval and the existing grounding policy. Graph paths stay behind the graph store port. Run status stays in the ingestion state machine. No published field is removed. `latest_warning` becomes empty for skip-only runs, which is a behavior change called out in the contract. | Pass |
| II. Security by design | Document filters and tenant filters stay on search, answer, and graph traversal. The browser journey reads credentials from the environment and does not log them. No production secret is read to write this plan. | Pass |
| III. Reliable ingestion | Upload, outbox, retries, and the parser child from Feature 001 stay. Optional skips remain successful stage statuses. Genuine warnings still finish the run as completed with warnings. | Pass |
| IV. Grounded GraphRAG | Citations must cover the quoted page. Evidence below the existing floor is not cited. Evaluation tests cover the fixture. Retrieval modes stay available. | Pass |
| V. Provider abstraction | No new model provider. The evidence floor does not call a model. | Pass |
| VI. Observability and cost | Worker logs keep the existing redaction. A liveness timeout is no longer the steady state of a healthy parse. Trace export remains the recorded constitution exception through 2027-01-31. | Exception unchanged |
| VII. Automated delivery and recovery | This feature adds tests and a browser journey. It does not practice a restore drill. That exception remains through 2027-01-31. Promotion stays on the existing gate. | Exception unchanged |
| VIII. FinOps | No new database, queue, or replica. | Pass |
| IX. Spec-driven delivery | This plan, research, data model, contracts, and tasks trace to `spec.md`. Implementation waits for review. | Pass |

## Project Structure

### Documentation (this feature)

```text
specs/002-rag-reliability-and-retrieval-quality/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── citation-and-evidence.schema.yaml
│   ├── graph-path.schema.yaml
│   ├── ingestion-warning.schema.yaml
│   └── release-identity.schema.yaml
├── checklists/requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
backend/src/graph_rag/
├── infrastructure/workers/main.py          # liveness off the ingestion lock
├── domain/citations/registry.py            # page range of the quoted passage
├── domain/retrieval/fusion.py              # normalized score stays a component
├── domain/generation/grounding_policy.py   # existing 0.12 floor
├── domain/policies/gate.py                 # empty evidence blocks pinned answers
├── application/retrieval/retrieve.py       # floor, phrase absence, structural paths
├── infrastructure/persistence/neo4j/       # tenant-scoped structural neighborhood
├── domain/ingestion/state_machine.py       # skip text is not a run warning
└── application/ingestion/                  # Feature 001 pipeline, unchanged upload

backend/tests/unit/                         # liveness, citation, floor, graph, warnings
backend/tests/evaluation/                   # four-page fixture quality check
frontend/e2e/                               # DEV browser journey, generated PDF
frontend/playwright.config.ts               # E2E_BASE_URL, no demo fallback on DEV
infra/k8s/worker/deployment.yaml            # probe timing stays; behavior moves to the process
infra/dev/release-gate.json                 # rollback identities; switches stay false
.github/workflows/                          # acceptance result matches product checks
```

**Structure Decision**: Extend the current tree. The worker command stays `enterprise-rag worker`. The upload routes in `backend/src/graph_rag/api/routes/documents.py` are not given a new intake flow.

## Design

### Worker liveness

`/health/live` today is an asyncio callback on the loop that runs `process_one` while holding `db_lock`. `/health/ready` may keep using that loop because it checks dependencies. Liveness moves to a handler that does not take `db_lock` and does not wait for the parse child. The existing `run_callable_isolated` child stays the parser boundary.

The probe in `infra/k8s/worker/deployment.yaml` keeps a 5-second timeout. Lengthening the timeout is not the fix. SIGTERM from an operator remains a clean stop. A healthy parse must not need that signal.

### Citation provenance

`evidence_to_citation` currently sets `page_end = page_start` when `page_end - page_start >= 3`. Remove that collapse. Parent and child passages already store `page_start` and `page_end` in `HierarchicalChunker`. Search and query both go through this citation builder for answers; search evidence already returns the stored range. After the change, both surfaces return that stored range. A citation whose text occurs only on a later page must include that page.

### Evidence floor

`assess_evidence` already uses `min_top_score` 0.12 on `RetrievedEvidence.score`. `apply_normalized_component` stores min-max in `score_components` and does not replace `score`. Search never calls the floor, so a pinned document always yields `top_k` hits. Retrieval drops candidates below 0.12 before assembly, and a pinned question whose distinctive phrase is absent from the selected passages returns no evidence even when a residual score remains. The query gate already blocks an empty pinned list. Search returns the same empty list plus a stable warning. RRF may still replace `score` with a rank score; the floor compares the pre-fusion retrieval score kept in `score_components`, not the rank score and not the min-max of a one-item list.

### Graph paths

`stage_extract_graph` upserts a semantic graph or, on failure and when semantic extraction is off, `StructuralGraphBuilder`. `_local` calls `resolve_entities` and otherwise returns dense hits with no path. When `include_graph_paths` is true and indexing stored nodes for the selected document, retrieval asks the graph store for a structural neighborhood of those document and chunk nodes. Entity neighborhood stays as it is when entities resolve. If neither walk returns nodes, the response warning is one of `graph_not_stored`, `graph_no_entity_match`, or `graph_no_structural_path`. An empty `graph_paths` list without one of those reasons fails the contract. Every query keeps the tenant parameter already required by the Neo4j adapter.

### Warnings

`mark_skipped` may keep the reason on the stage. `_has_warning_stages` and `progress()` ignore a warning whose stage status is `skipped`. `latest_warning` is the latest stage whose status is `completed_with_warnings`. Run status `completed_with_warnings` follows that set only. The existing unit test that expects a skip reason plus a parse warning to warn still expects a warning because of the parse warning; a new test covers a skip alone.

### Browser journey and acceptance

Playwright reads `E2E_BASE_URL`. When `E2E_TARGET=dev`, missing URL or credentials fail the process, and the built-in `admin@example.com` / `change-me-now-12` pair is not used. The PDF is generated in the test process with a standard PDF library. The journey asserts page 2 and document isolation. The job that runs it uses a runner that can open the DEV origin. Cloudflare error 1010 on a hosted runner is a failed job.

The acceptance workflow's Python blocks use matching openers and closers. A repository unit test parses those workflows. The job exits with the product-check status. Because repository dispatch reads the default branch, the reviewed workflow file is copied there as a workflow-only change and is not a feature merge and not an image promotion.

### Release identity

`infra/k8s/{api,worker,web}/kustomization.yaml` remains the serving digest. `infra/dev/release-gate.json` `rollback_digests` remains the rollback digest. Promotion switches stay false in this feature's specification change. A later promotion updates the serving digest and writes the displaced serving digest into `rollback_digests`. A later explicit rollback sets `rollback_in_effect` true and makes serving equal rollback. The unit test fails if a promotion commit writes the new digest into `rollback_digests`, and it fails if `rollback_in_effect` is false while serving equals rollback.

### Rollout

No step in this plan runs against the cluster. After review, the existing image and promotion workflows deploy the API and worker together, then the web image if the browser change is in it. The worker probe manifest does not need a digest change unless the deployment YAML itself changes. Rollback uses the gate's rollback digests. Feature 001's migration `0013_upload_sessions` stays applied.

## Complexity Tracking

No constitution principle is waived. The trace-export and restore exceptions stay the ones already recorded through 2027-01-31. They are not part of this feature's implementation.

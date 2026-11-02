# Tasks: RAG Reliability and Retrieval Quality

**Input**: Design documents from `/specs/002-rag-reliability-and-retrieval-quality/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Required. Each story's tests are written first and fail before the behavior change.

**Organization**: Tasks follow the user stories in spec.md. Feature 001 upload files are not task targets.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: User story from spec.md

## Phase 1: Freeze the accepted upload path

**Purpose**: Keep Feature 001's intake, object write, completion, and parser child out of this feature's edits.

- [x] T001 Add a unit test in `backend/tests/unit/test_feature_002_scope.py` that the upload session still commits before the presigned URL is returned and that `run_callable_isolated` still maps a child SIGILL to exit code 132
- [x] T002 [P] Record in that test that `infra/dev/release-gate.json` promotion switches are false and that this feature's tasks do not add an Alembic revision

---

## Phase 2: User Story 1 - Parsing stays up (Priority: P1)

**Goal**: Liveness answers within 5 seconds while synchronous work occupies the ingestion loop, a long stage keeps a persisted heartbeat, and a finished parse does not restart the worker.

**Independent Test**: `uv run pytest tests/unit/test_worker_liveness.py tests/unit/test_worker_heartbeat.py -q`

- [x] T003 [US1] Write `backend/tests/unit/test_worker_liveness.py` so synchronous work longer than 5 seconds still gets `/health/live` within 5 seconds, and an exited server does not answer. An await-under-lock test is not sufficient and must not be the only case
- [x] T004 [US1] Serve `/health/live` from an acceptor that is not the ingestion event loop in `backend/src/graph_rag/infrastructure/workers/main.py`. Dropping `db_lock` while remaining on that loop is not this task. Do not add Celery or change the Redis stream
- [x] T005 [US1] Keep `/health/ready` on the dependency checks in `backend/src/graph_rag/infrastructure/workers/main.py`
- [x] T006 [US1] Leave the 5-second liveness timeout in `infra/k8s/worker/deployment.yaml` and state in a comment there that a longer timeout is not the fix
- [x] T034 [US1] Write `backend/tests/unit/test_worker_heartbeat.py` and persist `heartbeat_at` at least every 60 seconds during a running stage from a session that is not the pipeline `AsyncSession` in `backend/src/graph_rag/infrastructure/workers/ingestion_worker.py`. A stage longer than 120 seconds is not stalled and is not reclaimed while that worker is alive. Do not write the heartbeat through the locked pipeline session

**Checkpoint**: SC-001 and SC-009 pass locally. No image is built.

---

## Phase 3: User Story 2 - A citation names the page it quotes (Priority: P1)

**Goal**: Parent and child citations use the stored page range, and search and answer agree.

**Independent Test**: `uv run pytest tests/unit/test_citation_page_range.py -q`

- [x] T007 [US2] Write `backend/tests/unit/test_citation_page_range.py` for a parent spanning pages 1–4 and children on pages 2, 3, and 4. The parent citation still covers the quoted page, the page-exact child remains beside the parent, and a neighbor keeps its own pages
- [x] T008 [US2] Remove the `page_end - page_start >= 3` collapse in `backend/src/graph_rag/domain/citations/registry.py`
- [x] T009 [US2] Assert in the same test that search evidence and the citation built from that evidence share `document_id`, `page_start`, and `page_end`

**Checkpoint**: SC-002 passes for the generated fixture. `HierarchicalChunker` page assignment stays.

---

## Phase 4: User Story 3 - An unsupported question returns no evidence (Priority: P1)

**Goal**: Search and answer share the 0.12 retriever-score floor, applied before expansion, and return no evidence when every selected passage is below it.

**Independent Test**: `uv run pytest tests/unit/test_retrieval_evidence_floor.py -q`

- [x] T010 [P] [US3] Write `backend/tests/unit/test_retrieval_evidence_floor.py` covering a below-floor retriever score, a one-item min-max of 1.0 that must not pass, a reciprocal-rank score that must not pass, an above-floor paraphrase that may pass, a second tenant receiving nothing, and the other document's sentence absent when that document's hits are below the floor. Do not assert that every non-verbatim question returns empty. Assign scores. Do not depend on a live cosine. Keep `test_vector_search_hides_other_tenant_chunks` green
- [x] T011 [US3] Keep the retriever score available for the floor in `backend/src/graph_rag/domain/retrieval/fusion.py` when reciprocal-rank fusion replaces `score`
- [x] T012 [US3] Filter below-floor passages in `backend/src/graph_rag/application/retrieval/retrieve.py` before `expand_parents_and_neighbors`, using the retriever or source score and 0.12 from `backend/src/graph_rag/domain/generation/grounding_policy.py`. Do not compare 0.12 to the reciprocal-rank score and do not filter on verbatim phrase absence alone
- [x] T013 [US3] Return `selection_has_no_supporting_evidence` from search in `backend/src/graph_rag/api/routes/retrieval.py` and from the pinned empty-evidence path in `backend/src/graph_rag/domain/policies/gate.py`
- [x] T014 [US3] Add the four-page case to `backend/tests/evaluation` without calling a live model unless `RUN_LIVE_OPENAI_TESTS=true`

**Checkpoint**: SC-003 passes. Existing `test_vector_search_hides_other_tenant_chunks` still passes.

---

## Phase 5: User Story 4 - A stored graph can be walked (Priority: P2)

**Goal**: A finished graph index yields a structural or entity path, or one explicit reason.

**Independent Test**: `uv run pytest tests/unit/test_structural_graph_paths.py -q`

- [x] T015 [US4] Write `backend/tests/unit/test_structural_graph_paths.py` for a structural document/passage graph, an entity neighborhood, a disabled graph store, and a second tenant
- [x] T016 [US4] Add a structural neighborhood filtered by tenant and by the selected `document_ids` on the graph store port and on `backend/src/graph_rag/infrastructure/persistence/neo4j/repository.py` and `backend/src/graph_rag/infrastructure/persistence/neo4j/memory.py`. A shared entity must not add another document's passages. Keep `test_local_graph_retrieval_respects_document_scope` and `test_local_graph_retrieval_returns_mentioned_chunks` green
- [x] T017 [US4] When `include_graph_paths` is true, return that path or `graph_not_stored`, `graph_no_entity_match`, or `graph_no_structural_path` from `backend/src/graph_rag/application/retrieval/retrieve.py`
- [x] T018 [US4] Put `path_kind` of `structural` or `entity` on `GraphPath.metadata` in `backend/src/graph_rag/domain/retrieval/models.py`

**Checkpoint**: SC-004 passes. `stage_extract_graph` still falls back to `StructuralGraphBuilder` after a semantic failure.

---

## Phase 6: User Story 5 - Optional skips are not warnings (Priority: P2)

**Goal**: Skip reasons stay on the stage. Genuine warnings set the run and `latest_warning`.

**Independent Test**: `uv run pytest tests/unit/test_ingestion_state_machine.py -q`

- [x] T019 [US5] Add a skip-only case and a `semantic_graph_failed` case to `backend/tests/unit/test_ingestion_state_machine.py`. Also cover a genuine warning whose text is not in the example prefix list, such as a document-intelligence miss
- [x] T020 [US5] Change `_has_warning_stages` and `progress` in `backend/src/graph_rag/domain/ingestion/state_machine.py` so a `skipped` stage does not set run status or `latest_warning`. Step status is authoritative. Do not classify by a closed prefix list
- [x] T021 [US5] Keep `test_happy_path_progress_and_finalize_gate` expecting `completed_with_warnings` because of the parse warning `low ocr`, not because of the skip reason
- [x] T035 [US5] Make `stage_extract_graph` in `backend/src/graph_rag/application/ingestion/stage_pipeline.py` return `completed_with_warnings` with `semantic_graph_failed` on that stage. Do not leave the failure only on `raw.warnings`

**Checkpoint**: SC-005 passes. The graph step carries `semantic_graph_failed`. Community summarization stays disabled.

---

## Phase 7: User Story 6 - The browser journey can be repeated against DEV (Priority: P2)

**Goal**: One Playwright journey uploads a generated multipage PDF and checks a page citation. DEV credentials are required only when `E2E_TARGET=dev`.

**Independent Test**: `cd frontend && npx playwright test e2e/rag-citation.spec.ts`

- [x] T022 [P] [US6] Add `frontend/e2e/rag-citation.spec.ts` that generates a four-page PDF, uploads it through the existing session flow, and asserts a page-2 citation for that document only
- [x] T023 [US6] Update `frontend/playwright.config.ts` and the spec so `E2E_TARGET=dev` fails closed without `E2E_BASE_URL`, `E2E_ADMIN_EMAIL`, `E2E_ADMIN_PASSWORD`, and `E2E_TENANT_KEY`
- [x] T024 [US6] Remove the hand-built PDF body from the citation journey. Leave `frontend/e2e/upload-journey.spec.ts` on its local upload check unless it also claims page provenance
- [x] T025 [US6] Document the DEV command in `specs/002-rag-reliability-and-retrieval-quality/quickstart.md` and do not commit credentials. State that the journey runs after this feature's web image is deployed and that serving web digest `sha256:eb34e619be4107352fbb0ce3e543e8b368865059746060809589afe6d290dc84` is not that image

**Checkpoint**: The local journey passes. The DEV journey is not run against today's web image. A runner that cannot open the origin fails rather than skipping. An in-cluster API call is not a pass.

---

## Phase 8: User Story 7 - Acceptance and rollback identities agree (Priority: P2)

**Goal**: Serving and rollback digests are both checked. The acceptance job result is the product-check result.

**Independent Test**: `uv run pytest tests/unit/test_release_identity.py tests/unit/test_workflow_heredoc.py -q`

- [x] T026 [P] [US7] Add `backend/tests/unit/test_release_identity.py` that reads `infra/k8s/api/kustomization.yaml`, `infra/k8s/worker/kustomization.yaml`, `infra/k8s/web/kustomization.yaml`, and `infra/dev/release-gate.json`, and fails when `rollback_in_effect` is false while a serving digest equals its rollback digest. Compare inequality. Do not hardcode today's serving digest as a permanent expected value. Keep `test_release_gate_stays_closed_and_records_rollback_digests` green
- [x] T027 [US7] Add `rollback_in_effect: false` to `infra/dev/release-gate.json` without changing `promote` or `rollback_digests`. This specification review does not edit that file
- [x] T028 [P] [US7] Add `backend/tests/unit/test_workflow_heredoc.py` that every Python heredoc in `.github/workflows/*.yml` closes with the token that opened it, and that an in-test fixture opened with `CHK` and closed with `PY` fails. `accept-dev-feature-001.yml` is on the default branch and is not on this branch, so a directory scan alone cannot see that bug
- [x] T029 [US7] Add `.github/workflows/accept-dev-feature-002.yml` whose final exit status is the product-check status, which generates the PDF with a standard library, and which does not promote an image
- [ ] T030 [US7] When that workflow is dispatched, copy only the workflow file to the default branch. Do not merge this feature and do not promote an image

**Checkpoint**: SC-007 passes locally. SC-008 stays blocked until a reviewed promotion.

---

## Phase 9: Polish

- [x] T031 [P] Run `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy src`, and `uv run pytest tests/unit` from `backend/`
- [x] T032 [P] Run frontend `tsc` and Vitest for the browser helper changes
- [x] T033 Confirm `specs/001-reliable-upload-ingestion/acceptance.md` still names the serving digests and points at this feature for the open gaps

---

## Dependencies & Execution Order

### Phase Dependencies

- Phase 1 is the freeze and can start immediately.
- User Stories 1, 2, 5, and 7 can start after Phase 1 in parallel.
- User Story 3 depends on the citation test fixture shape from User Story 2 and can share that fixture.
- User Story 4 can start after Phase 1. It does not depend on the evidence floor.
- User Story 6 depends on the page and no-evidence behavior from User Stories 2 and 3 for its DEV assertion, and can be written against local fakes earlier.
- Polish follows the stories that are included in the review.

### Parallel Opportunities

- T003, T007, T010, T015, T019, T022, T026, T028, and T034 touch different new test files and can be written together.
- Implementation of liveness, citations, warnings, and release identity then proceeds in those separate files.

## Implementation Strategy

1. Finish Phase 1 so the upload path is locked by a test.
2. Deliver User Stories 1, 2, and 3 as the correctness MVP. Stop and run their tests.
3. Add User Stories 4 and 5. Stop and run their tests.
4. Add User Stories 6 and 7 without dispatching DEV or promotion.
5. Review the feature. Only then use the existing image and promotion workflows.

## Notes

- This task list does not authorize a DEV deploy or a merge.
- Parser package versions stay pinned.
- Community summarization stays skipped.
- T027 and T029 are done. T030 is not: the workflow was not dispatched and was not copied to the default branch.

## Completion evidence

Recorded 2 November 2026, 15:01 Europe/Paris. No image was built, no digest was changed, and PR #44 was not merged.

| Check | Result |
| --- | --- |
| Feature unit tests (`test_feature_002_scope.py`, liveness, heartbeat, citations, evidence floor, graph paths, state machine, graph-stage warning, release identity, heredoc, search HTTP, worker health) | Passed with the full unit suite |
| `uv run pytest tests/unit --ignore=tests/unit/test_docling_adapter_bounding_boxes.py -q` | 615 passed |
| `uv run pytest tests/unit/test_docling_adapter_bounding_boxes.py -q` after `uv sync --all-extras` | Passed |
| `uv run pytest tests/evaluation/test_four_page_evidence_floor.py -q` | Passed. No live model |
| `uv run pytest tests/integration -q` | 23 passed, 9 skipped. Compose Postgres, Redis, and MinIO were not listening |
| Feature-file `ruff format --check` and `ruff check` | Passed |
| `uv run ruff check .` and `uv run mypy src` from `backend/` | Pre-existing failures remain outside this feature (179 ruff findings, 156 mypy errors). None are in the feature files |
| `npx tsc --noEmit` and `npx vitest run` from `frontend/` | `tsc` passed. Vitest: 5 files, 17 tests passed |
| `E2E_TARGET=dev npx playwright test e2e/rag-citation.spec.ts --list` | Exit 1 before login: missing `E2E_BASE_URL`, `E2E_ADMIN_EMAIL`, `E2E_ADMIN_PASSWORD`, `E2E_TENANT_KEY` |
| Live Playwright upload | Not run. Docker is not available, so the API, object store, and web app were not started. The citation spec generates its PDF with fpdf2 and does not inline a PDF body |
| Acceptance workflow PDF generator | Executed locally. It wrote a 4-page PDF (1515 bytes) and does not promote an image |
| `specs/001-reliable-upload-ingestion/acceptance.md` | Still names serving digests `sha256:5abf5b69…`, `sha256:17eb0f6f…`, and `sha256:eb34e619…`, and points the open gaps at feature 002 |

T030 stays open until a reviewed dispatch copies only `.github/workflows/accept-dev-feature-002.yml` to the default branch.

## Requirement coverage

Every functional requirement and success criterion maps to a task. Tests are written before the behavior change.

| Requirement | Tasks |
| --- | --- |
| FR-001 | T003, T004, T006 |
| FR-002 | T003 |
| FR-003 | T003, T004, T006 |
| FR-004 | T001, T002 |
| FR-005 | T007, T008, T009 |
| FR-006 | T007, T008 |
| FR-007 | T007, T008 |
| FR-008 | T010, T011, T012, T013 |
| FR-009 | T010, T012, T013 |
| FR-010 | T010, T011, T012 |
| FR-011 | T010, T015, T016 |
| FR-012 | T015, T016, T017 |
| FR-013 | T015, T016, T017, T018 |
| FR-014 | T019, T020 |
| FR-015 | T019, T020, T021, T035 |
| FR-016 | T021, T033 |
| FR-017 | T022, T024, T025 |
| FR-018 | T023, T025 |
| FR-019 | T026, T027, T028, T029, T030 |
| FR-020 | T001, T004 |
| FR-021 | T034 |
| SC-001 | T003, T004, T006 |
| SC-002 | T007, T008, T009 |
| SC-003 | T010, T011, T012, T013, T014 |
| SC-004 | T015, T016, T017, T018 |
| SC-005 | T019, T020, T021, T035 |
| SC-006 | T022, T023, T024, T025 |
| SC-007 | T026, T027, T028, T029 |
| SC-008 | T030, T031, T033 |
| SC-009 | T034 |

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

- [ ] T001 Add a unit test in `backend/tests/unit/test_feature_002_scope.py` that the upload session still commits before the presigned URL is returned and that `run_callable_isolated` still maps a child SIGILL to exit code 132
- [ ] T002 [P] Record in that test that `infra/dev/release-gate.json` promotion switches are false and that this feature's tasks do not add an Alembic revision

---

## Phase 2: User Story 1 - Parsing stays up (Priority: P1)

**Goal**: Liveness answers within 5 seconds while a parse holds the worker, and a finished parse does not restart it.

**Independent Test**: `uv run pytest tests/unit/test_worker_liveness.py -q`

- [ ] T003 [US1] Write `backend/tests/unit/test_worker_liveness.py` so a held processing tick still gets `/health/live` within 5 seconds, and an exited server does not answer
- [ ] T004 [US1] Serve `/health/live` in `backend/src/graph_rag/infrastructure/workers/main.py` without taking `db_lock` and without waiting on `process_one`
- [ ] T005 [US1] Keep `/health/ready` on the dependency checks in `backend/src/graph_rag/infrastructure/workers/main.py`
- [ ] T006 [US1] Leave the 5-second liveness timeout in `infra/k8s/worker/deployment.yaml` and state in a comment there that a longer timeout is not the fix

**Checkpoint**: SC-001 passes locally. No image is built.

---

## Phase 3: User Story 2 - A citation names the page it quotes (Priority: P1)

**Goal**: Parent and child citations use the stored page range, and search and answer agree.

**Independent Test**: `uv run pytest tests/unit/test_citation_page_range.py -q`

- [ ] T007 [US2] Write `backend/tests/unit/test_citation_page_range.py` for a parent spanning pages 1–4 and children on pages 2, 3, and 4, asserting the citation range includes the page that contains the quoted sentence
- [ ] T008 [US2] Remove the `page_end - page_start >= 3` collapse in `backend/src/graph_rag/domain/citations/registry.py`
- [ ] T009 [US2] Assert in the same test that search evidence and the citation built from that evidence share `document_id`, `page_start`, and `page_end`

**Checkpoint**: SC-002 passes for the generated fixture. `HierarchicalChunker` page assignment stays.

---

## Phase 4: User Story 3 - An unsupported question returns no evidence (Priority: P1)

**Goal**: Search and answer share the 0.12 retrieval-score floor and return no evidence when the distinctive phrase is absent.

**Independent Test**: `uv run pytest tests/unit/test_retrieval_evidence_floor.py -q`

- [ ] T010 [P] [US3] Write `backend/tests/unit/test_retrieval_evidence_floor.py` covering a below-floor score, a one-item min-max of 1.0 that must not pass the floor, a missing distinctive phrase inside a pinned document, a hit inside the document that contains the phrase, and a second tenant receiving nothing
- [ ] T011 [US3] Keep the retrieval score available for the floor in `backend/src/graph_rag/domain/retrieval/fusion.py` when reciprocal-rank fusion replaces `score`
- [ ] T012 [US3] Filter below-floor passages and phrase misses in `backend/src/graph_rag/application/retrieval/retrieve.py` before assembly, using 0.12 from `backend/src/graph_rag/domain/generation/grounding_policy.py`
- [ ] T013 [US3] Return `selection_has_no_supporting_evidence` from search in `backend/src/graph_rag/api/routes/retrieval.py` and from the pinned empty-evidence path in `backend/src/graph_rag/domain/policies/gate.py`
- [ ] T014 [US3] Add the four-page case to `backend/tests/evaluation` without calling a live model unless `RUN_LIVE_OPENAI_TESTS=true`

**Checkpoint**: SC-003 passes. Existing `test_vector_search_hides_other_tenant_chunks` still passes.

---

## Phase 5: User Story 4 - A stored graph can be walked (Priority: P2)

**Goal**: A finished graph index yields a structural or entity path, or one explicit reason.

**Independent Test**: `uv run pytest tests/unit/test_structural_graph_paths.py -q`

- [ ] T015 [US4] Write `backend/tests/unit/test_structural_graph_paths.py` for a structural document/passage graph, an entity neighborhood, a disabled graph store, and a second tenant
- [ ] T016 [US4] Add a tenant-scoped structural neighborhood on the graph store port and on `backend/src/graph_rag/infrastructure/persistence/neo4j/repository.py` and `backend/src/graph_rag/infrastructure/persistence/neo4j/memory.py`
- [ ] T017 [US4] When `include_graph_paths` is true, return that path or `graph_not_stored`, `graph_no_entity_match`, or `graph_no_structural_path` from `backend/src/graph_rag/application/retrieval/retrieve.py`
- [ ] T018 [US4] Put `path_kind` of `structural` or `entity` on `GraphPath.metadata` in `backend/src/graph_rag/domain/retrieval/models.py`

**Checkpoint**: SC-004 passes. `stage_extract_graph` still falls back to `StructuralGraphBuilder` after a semantic failure.

---

## Phase 6: User Story 5 - Optional skips are not warnings (Priority: P2)

**Goal**: Skip reasons stay on the stage. Genuine warnings set the run and `latest_warning`.

**Independent Test**: `uv run pytest tests/unit/test_ingestion_state_machine.py -q`

- [ ] T019 [US5] Add a skip-only case and a `semantic_graph_failed` case to `backend/tests/unit/test_ingestion_state_machine.py`
- [ ] T020 [US5] Change `_has_warning_stages` and `progress` in `backend/src/graph_rag/domain/ingestion/state_machine.py` so a `skipped` stage does not set run status or `latest_warning`
- [ ] T021 [US5] Keep `test_happy_path_progress_and_finalize_gate` expecting `completed_with_warnings` because of the parse warning `low ocr`, not because of the skip reason

**Checkpoint**: SC-005 passes. Community summarization stays disabled.

---

## Phase 7: User Story 6 - The browser journey can be repeated against DEV (Priority: P2)

**Goal**: One Playwright journey uploads a generated multipage PDF and checks a page citation. DEV credentials are required only when `E2E_TARGET=dev`.

**Independent Test**: `cd frontend && npx playwright test e2e/rag-citation.spec.ts`

- [ ] T022 [P] [US6] Add `frontend/e2e/rag-citation.spec.ts` that generates a four-page PDF, uploads it through the existing session flow, and asserts a page-2 citation for that document only
- [ ] T023 [US6] Update `frontend/playwright.config.ts` and the spec so `E2E_TARGET=dev` fails closed without `E2E_BASE_URL`, `E2E_ADMIN_EMAIL`, `E2E_ADMIN_PASSWORD`, and `E2E_TENANT_KEY`
- [ ] T024 [US6] Remove the hand-built PDF body from the citation journey. Leave `frontend/e2e/upload-journey.spec.ts` on its local upload check unless it also claims page provenance
- [ ] T025 [US6] Document the DEV command in `specs/002-rag-reliability-and-retrieval-quality/quickstart.md` and do not commit credentials

**Checkpoint**: The local journey passes. The DEV journey is not run from this task until review, and a runner that cannot open the origin fails rather than skipping.

---

## Phase 8: User Story 7 - Acceptance and rollback identities agree (Priority: P2)

**Goal**: Serving and rollback digests are both checked. The acceptance job result is the product-check result.

**Independent Test**: `uv run pytest tests/unit/test_release_identity.py tests/unit/test_workflow_heredoc.py -q`

- [ ] T026 [P] [US7] Add `backend/tests/unit/test_release_identity.py` that reads `infra/k8s/api/kustomization.yaml`, `infra/k8s/worker/kustomization.yaml`, `infra/k8s/web/kustomization.yaml`, and `infra/dev/release-gate.json`, and fails when `rollback_in_effect` is false while a serving digest equals its rollback digest
- [ ] T027 [US7] Add `rollback_in_effect: false` to `infra/dev/release-gate.json` without changing `promote` or `rollback_digests`
- [ ] T028 [P] [US7] Add `backend/tests/unit/test_workflow_heredoc.py` that every Python heredoc in `.github/workflows/*.yml` closes with the token that opened it
- [ ] T029 [US7] Add `.github/workflows/accept-dev-feature-002.yml` whose final exit status is the product-check status, which generates the PDF with a standard library, and which does not promote an image
- [ ] T030 [US7] When that workflow is dispatched, copy only the workflow file to the default branch. Do not merge this feature and do not promote an image

**Checkpoint**: SC-007 passes locally. SC-008 stays blocked until a reviewed promotion.

---

## Phase 9: Polish

- [ ] T031 [P] Run `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy src`, and `uv run pytest tests/unit` from `backend/`
- [ ] T032 [P] Run frontend `tsc` and Vitest for the browser helper changes
- [ ] T033 Confirm `specs/001-reliable-upload-ingestion/acceptance.md` still names the serving digests and points at this feature for the open gaps

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

- T003, T007, T010, T015, T019, T022, T026, and T028 touch different new test files and can be written together.
- Implementation of liveness, citations, warnings, and release identity then proceeds in those separate files.

## Implementation Strategy

1. Finish Phase 1 so the upload path is locked by a test.
2. Deliver User Stories 1, 2, and 3 as the correctness MVP. Stop and run their tests.
3. Add User Stories 4 and 5. Stop and run their tests.
4. Add User Stories 6 and 7 without dispatching DEV or promotion.
5. Review the feature. Only then use the existing image and promotion workflows.

## Notes

- This task list does not authorize a DEV deploy.
- Parser package versions stay pinned.
- Community summarization stays skipped.

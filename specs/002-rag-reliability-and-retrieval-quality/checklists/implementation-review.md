# Implementation review: RAG Reliability and Retrieval Quality

**Date**: 2 November 2026, 15:22 Europe/Paris

**Commit reviewed**: `b2b4c34` (`feat(002): keep worker liveness and retrieval provenance reliable`)

**Follow-up in this review**: the evaluation loader now resolves `data/evaluation/corpus` and `data/evaluation/questions.json`. That path fix is the only application change in this pass.

**Pull request**: #44, branch `cursor/002-rag-reliability-and-retrieval-quality-7784`, base `dev`

**Compared with**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `tasks.md` T001–T035, the four contracts, and the worker, retrieval, citation, graph, warning, and release-gate code.

**Left untouched**: `infra/dev/release-gate.json` promotion switches and `rollback_digests`, the serving digests in `infra/k8s/*/kustomization.yaml`, image builds, DEV workflow dispatch, and merge of pull request #44. `rollback_in_effect` remains `false`.

## Recommendation

**NO-GO** for the next phase. That phase is a merge of pull request #44, an image build, a digest promotion, or a DEV acceptance dispatch.

**NO-GO** for treating FR-008 as complete on multi-mode retrieval. A second reciprocal-rank fusion overwrites `source_score_0` with the inner rank score, and the 0.12 floor then drops an above-floor dense passage.

**Still explicitly open**: T030, and the live DEV browser journey (FR-017, SC-006). SC-008 stays failed while those are open and while the floor defect stands.

The branch can stay open for a follow-up that fixes the floor overwrite and adds a regression test. That follow-up is not a promotion.

## Blockers

| Blocker | Evidence | What remains |
| --- | --- | --- |
| Multi-mode evidence floor compares 0.12 to a reciprocal-rank score | Domain functions, this review. Inner fusion of a dense score 0.80 stores `source_score_0 = 0.80` and replaces `score` with about 0.01639. Outer fusion copies that item and then writes `source_score_0 = 0.01639`. `retriever_score` returns 0.01639 and `at_or_above_evidence_floor` is false. The citation contract says the comparison uses `source_score_*` and does not use a reciprocal-rank score. | Fix fusion so an already stored retriever score survives a second fusion. Add a test where hybrid output is fused with another mode and a 0.80 dense passage stays. Single-mode hybrid is unaffected: the same 0.80 still passes after one fusion. |
| T030 is open | `tasks.md` still has `- [ ] T030`. `git cat-file -e origin/main:.github/workflows/accept-dev-feature-002.yml` fails: the file is absent from `origin/main` after `git fetch origin main` on 2 November 2026. The workflow on this branch was not dispatched. | A later workflow-only copy onto the default branch, after review. No feature merge and no image promotion. |
| Live DEV browser acceptance is open | `E2E_TARGET=dev npx playwright test e2e/rag-citation.spec.ts --list` exits 1 before login because `E2E_BASE_URL`, `E2E_ADMIN_EMAIL`, `E2E_ADMIN_PASSWORD`, and `E2E_TENANT_KEY` are missing. The live upload was not run. Docker is not available in this environment. Serving web digest `sha256:eb34e619be4107352fbb0ce3e543e8b368865059746060809589afe6d290dc84` is not this feature's web image. | Run the documented journey after this feature's web image is deployed. A pass against today's web image does not meet FR-017 or SC-006. |
| SC-008 | The feature is not releasable while SC-003's above-floor path fails under multi-mode fusion, or while SC-006 has not been run against this feature's web image. | Close the rows above on the existing delivery path. This review does not deploy. |
| Two Redis integration tests are absent from CI | Named below. `validate-feature.yml`, `build-and-push-api-image.yml`, and `build-and-push-worker-image.yml` run `uv run pytest tests/unit -q` only. | Run `test_restarted_worker_finishes_the_unacked_run` and `test_republish_after_restart_is_exactly_once` in CI before any promotion. They were skipped here because Compose Redis was down. That skip is not a failure. |

## Incomplete requirements

| Requirement | Status |
| --- | --- |
| FR-008, and the citation-contract rule that 0.12 is not compared to a reciprocal-rank score | Incomplete on every search that selects more than one mode. `select_modes` does that for factual, assay, multimodal, and MIX queries. AUTO with no labels selects hybrid only, and that single fusion keeps the original source score. |
| FR-009, FR-010 | Met on the paths the unit tests cover: empty assembled evidence always adds `weak_evidence` and `selection_has_no_supporting_evidence`; search appends the selection warning when evidence is empty; the gate adds it and still blocks a pinned empty list with `build_scope_miss_message`. Supplemental coverage filters with the same floor before assembly. |
| FR-017, SC-006 | The Playwright spec, fail-closed config, and quickstart exist. The live DEV run does not. |
| FR-019 | Local release-identity and heredoc checks exist. The acceptance workflow's last step is the product-check pytest, and it does not promote. T030, the default-branch copy, is not done. |
| FR-021, SC-009 | The heartbeat interval is capped at 60 seconds and `persist_heartbeat` uses `db_session_factory`, refuses the pipeline session, and updates `heartbeat_at` and `worker_id` only. Reclaim requires both a stale persisted heartbeat (default 90 seconds) and Redis pending idle (default 120 seconds). A fresh heartbeat is not reclaimed. The unit test uses a fake persister, not Postgres or Redis. |
| SC-001 | The liveness mechanism is implemented. The automated trial is one `time.sleep(6)` on the ingestion loop with three live probes, not three CPU-heavy parser runs. |
| SC-002, SC-004, SC-005, SC-007 | Met by the unit tests cited below, within the limits in the debt section. |
| T001–T029, T031–T035 | Checked in `tasks.md`. This review does not uncheck them. |
| T030 | Unchecked. This review does not check it. |

## Worker liveness, heartbeat, reclaim, shutdown

`/health/live` is served by `ThreadingHTTPServer` on thread `worker-health` in `start_health_acceptor`. The handler returns 200 before any asyncio call. `/health/ready` calls `_ready_from_container`, which schedules the dependency checks on the ingestion loop and waits at most 4 seconds. A blocked loop fails readiness and still answers liveness. `infra/k8s/worker/deployment.yaml` keeps `timeoutSeconds: 5` and states that a longer timeout is not the fix.

`run_worker` holds `db_lock` around `process_one` and around the outbox publisher so those two coroutines do not share the pipeline session. The heartbeat task is a third writer. It opens `container.db_session_factory()`, and `touch_heartbeat` runs `set_tenant_context` and updates only `heartbeat_at` and `worker_id`. A memory backend leaves `session_factory` as `None`, and the persister returns without writing.

`process_one` reloads the run after `_execute` and before the final `persist_run`, so the in-memory heartbeat object is not written back over the pipeline result. Stage completion still calls `update_run`, which writes every column including `heartbeat_at`. That stamp is `now()` at the stage boundary, so it refreshes the row. It can overwrite an intermediate touch with a newer stamp. The vision enrichment callback still calls `update_run` on the pipeline session. That write is sequential with the stage and concurrent with the independent heartbeat session.

SIGTERM and SIGINT call `worker.request_stop()` and set the stop event. Probe kill and operator stop both arrive as SIGTERM. The process does not distinguish them. `health_server.shutdown()` runs in `finally` on the ingestion loop. The acceptor is another thread, so an in-flight readiness probe does not hold that shutdown. The probe's own wait is the 4-second `future.result` timeout.

The heartbeat loop has no exception handler. `process_one` cancels it in `finally` and suppresses only `CancelledError`. A persist failure therefore leaves `process_one`, releases `db_lock`, and leaves `run_worker`, because the worker loop does not catch that exception. The pod would then fail liveness and restart. That is recorded as debt below. The success path still acknowledges only a successful terminal status and leaves a non-terminal run unacked.

## Evidence floor, citations, and tenant isolation

The floor constant is `EVIDENCE_SCORE_FLOOR = 0.12`. `retriever_score` uses the maximum `source_score_*` when those keys exist, and otherwise `item.score`. One-item min-max stays in `score_components["normalized"]` and is not the floor input. `_retrieve_inner` filters after fusion and before rerank, boosts, and `expand_parents_and_neighbors`. Expanded neighbors are not filtered again. Their score is reduced and may sit below 0.12. That matches the approved rule that the floor applies to retriever hits before expansion.

`evidence_to_citation` copies `page_start` and `page_end`. The `page_end - page_start >= 3` collapse is gone. Search evidence and the citation built from it share `document_id`, `page_start`, and `page_end`.

Graph-local evidence uses a fixed score of 0.8, so it passes the floor. Tenant and document filters remain on vector search, lexical search, structural neighborhood, and `_filter_to_requested_documents`. `structural_neighborhood_cypher` binds `tenant_id` and `document_id IN $document_ids`. The Neo4j repository drops a row whose `document_id` is outside that set. The memory store does the same. An empty `document_ids` list returns no structural hits, so an unscoped request does not walk other documents.

Lexical search stores the raw lexical score on `item.score` and under `score_components["lexical"]`. That score is not a 0–1 cosine. On a single hybrid branch, `max(source_score_*)` can therefore pass 0.12 from the lexical score while the dense score is below 0.12. After a second fusion, a lexical value stored as `source_score_1` can survive the overwrite that destroys `source_score_0`. Both are residual risks. The overwrite of an above-floor dense score is the blocker.

## Graph traversal and warnings

When `include_graph_paths` is false, `_graph_paths_or_reason` adds no warning. Existing paths are kept. A missing graph store yields `graph_not_stored`. A structural hit yields one path with `metadata.path_kind = structural` and nodes `{label}:{node_id}`. Otherwise an entity mention yields `graph_no_entity_match`, and the remaining case yields `graph_no_structural_path`. Entity-local paths use `path_kind: entity`. Global topic paths also use `path_kind: entity`, which is the contract enum.

`stage_extract_graph` catches a semantic build failure, appends `semantic_graph_failed:{ExcName}` to `raw.warnings`, falls back to `StructuralGraphBuilder`, and returns `COMPLETED_WITH_WARNINGS` with that warning on the stage. Any exception in that `try` uses the same label.

`progress` and `_has_warning_stages` read `COMPLETED_WITH_WARNINGS` only. A skipped stage keeps its reason on the stage and does not set run status or `latest_warning`. Optional idle reasons stay skips, including `community summarization disabled`. A skip-only run finishes as `completed` with an empty latest warning. `test_happy_path_progress_and_finalize_gate` still expects `completed_with_warnings` because of the parse warning `low ocr`.

## Backward compatibility and release identity

The selection warning is an additional string. The pinned scope-miss sentence is still `build_scope_miss_message`. No Alembic revision was added. The queue remains Redis Streams `ingestion-jobs` with group `ingestion-workers`. Parser isolation and the upload-session commit stay covered by `test_feature_002_scope.py`.

`rollback_in_effect` is `false`. `promote.api`, `promote.worker`, and `promote.web` are `false`. Rollback digests are unchanged: API `sha256:b87a4646ea022aec2639e4f25e3969bd6c42e69735d96847d98e982383e44385`, worker `sha256:fdf5406658e3b12845efccb00a77a0ac41cbeab7572d7e54d7ad388702dcf5af`, web `sha256:690e22dff639dd779e8bca39bb3deb16d93a7d79036e4936170ec38a06746571`. Serving digests were not edited. Equality of a serving digest and its rollback digest is rejected by `test_release_identity.py` while `rollback_in_effect` is false. The test does not hardcode today's serving digest.

`.github/workflows/accept-dev-feature-002.yml` generates a four-page PDF with the standard library and ends on pytest. The job exit is the product-check exit. It does not promote.

## Skipped integration tests

`uv run pytest tests/integration -q -rs` on 2 November 2026: **23 passed, 9 skipped**. Compose services were not started. The 23 that passed include the in-memory reclaim, duplicate-delivery, and graceful-shutdown cases in `test_ingest_worker_reliability.py`.

| Test | Skip reason | CI requirement |
| --- | --- | --- |
| `test_worker_crash_recovery.py::test_restarted_worker_finishes_the_unacked_run` | Isolated Compose Redis is not listening on 127.0.0.1:6380 | Must run in CI before promotion. It is the Redis-stream check that a restarted worker finishes an unacked run. |
| `test_outbox_restart.py::test_republish_after_restart_is_exactly_once` | Isolated Compose Redis is not listening on 127.0.0.1:6380 | Must run in CI before promotion. It is the Redis check that republish after restart is exactly once. |
| `test_quota_reservations.py::test_concurrent_reserves_share_one_budget` | Compose Postgres is not listening on 127.0.0.1:5433 | Feature 001 quota coverage. Not a new Feature 002 blocker. Not in CI today. |
| `test_upload_session_migration.py::test_upgrade_and_downgrade_keep_existing_documents` | Compose Postgres is not listening on 127.0.0.1:5433 | Feature 001 migration coverage. Not a new Feature 002 blocker. Not in CI today. |
| `test_minio_direct_upload.py::test_staging_put_does_not_replace_final_object` | Compose MinIO is not listening on 127.0.0.1:9000 | Feature 001 object-store coverage. Not a new Feature 002 blocker. |
| `test_upload_concurrent_100mb.py::test_two_concurrent_hundred_megabyte_uploads` | Compose MinIO is not listening on 127.0.0.1:9000 | Feature 001 object-store coverage. Not a new Feature 002 blocker. |
| `test_upload_direct_minio.py::test_hundred_megabyte_put_finishes_within_30_seconds` | Compose MinIO is not listening on 127.0.0.1:9000 | Feature 001 object-store coverage. Not a new Feature 002 blocker. |
| `test_azure_blob_presign_put.py::test_presign_put_is_scoped_to_the_staging_key` | Azurite is not listening on 127.0.0.1:10000 | Feature 001 Azure staging coverage. Not a new Feature 002 blocker. |
| `test_azure_blob_presign_put.py::test_zero_byte_copy_is_rejected_and_not_reported_as_one_byte` | Azurite is not listening on 127.0.0.1:10000 | Feature 001 Azure staging coverage. Not a new Feature 002 blocker. |

## Checks run in this review

Recorded 2 November 2026, 15:22 Europe/Paris. No image was built and no workflow was dispatched.

| Check | Result |
| --- | --- |
| `uv run pytest tests/evaluation -q` | 5 passed, including `test_corpus_files_exist`, `test_questions_load`, and `test_offline_evaluation_harness` |
| `uv run pytest tests/unit -q` | 621 passed in 137.83 seconds. This includes the Docling bounding-box tests |
| `uv run pytest tests/integration -q -rs` | 23 passed, 9 skipped, names above |
| `uv run ruff format --check` and `uv run ruff check` on the corpus loader and the harness test | Passed |
| `uv run ruff check .` from `backend/` | 179 findings, the same pre-existing baseline. The corpus loader is not among them |
| `uv run mypy src` from `backend/` | 156 errors, the same pre-existing baseline |
| `npx tsc --noEmit` and `npx vitest run` from `frontend/` | `tsc` passed. Vitest: 5 files, 17 tests passed |
| `E2E_TARGET=dev npx playwright test e2e/rag-citation.spec.ts --list` | Exit 1 before login |
| `origin/main` workflow file | Absent |

## Evaluation harness fix

`default_corpus_dir` and `default_questions_path` used `Path(__file__).parents[4]`, which is `backend/`, then `evaluation/corpus` and `evaluation/questions.json`. The files live at `data/evaluation/corpus` and `data/evaluation/questions.json`. The loader now uses `parents[5]`, the repository root. `test_corpus_files_exist` resolves `data/examples/sample.pdf` from the test file, so the assertion does not depend on the pytest working directory. `docs/evaluation.md` now names those paths.

`backend/scripts/generate_rag_challenge.py` and `data/reports/rag-reliability-report.md` still say `evaluation/corpus/`. `backend/tests/unit/test_pdf_line_splitting.py` still opens `../data/evaluation/corpus/text_heavy.pdf` relative to the process cwd. Those references are debt. `backend/scripts/evaluate_rag.py` already points at `../data/evaluation/corpus`.

## Non-blocking technical debt

- A heartbeat persist failure cancels cleanup of the message: ack and dead-letter are skipped, and the worker process exits. The loop should catch that error, keep the message unacked, and keep serving liveness.
- Lexical scores are unbounded. A hybrid hit can clear 0.12 on the lexical source score while the dense score is below the floor. The floor tests assign cosine-like scores and do not cover this scale.
- SC-001 is evidenced by one blocked sleep, not by three parser invocations in one process.
- SC-007 checks the closed gate and digest inequality. It does not simulate a promotion.
- Vision enrichment still persists the full run on the pipeline session.
- Structural paths require `document_ids`. An unscoped graph request receives `graph_no_structural_path` or `graph_no_entity_match` instead of a tenant-wide walk.
- Expanded neighbors may sit below 0.12. The contract applies the floor before expansion.
- The full ruff and mypy baselines (179 and 156) are unchanged and were not mass-fixed.
- The seven Postgres, MinIO, and Azurite skips above are Feature 001 service tests. They are not in CI. They were not executed in this review.
- `generate_rag_challenge.py` and `data/reports/rag-reliability-report.md` still name the old corpus directory.

## Security, concurrency, and regression notes

Heartbeat and pipeline sessions are distinct on the Postgres backend, and `touch_heartbeat` sets the tenant context before the update. Structural Cypher is parameterized. The repository drops rows outside the requested documents. No new queue, schema, or credential was added. The scope-miss sentence is unchanged.

The concurrency risk that remains is the uncaught heartbeat exception, plus the vision stage writing the full row on the pipeline session while the heartbeat session updates the same row. The stage-end `update_run` sets `heartbeat_at` to the current time, so it does not reintroduce a stale stamp. It can still race the independent touch.

The regression that blocks the next phase is the second fusion dropping an above-floor dense passage. Neighbor expansion below 0.12 and the lexical score scale are the other retrieval behavior changes to watch. Skip-only runs now finish as `completed` with an empty `latest_warning`. Feature 001 acceptance accepts both `completed` and `completed_with_warnings`.

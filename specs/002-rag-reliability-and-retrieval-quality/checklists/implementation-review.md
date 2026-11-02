# Implementation review: RAG Reliability and Retrieval Quality

**Updated**: 2 November 2026, 18:34 Europe/Paris

**Branch**: `cursor/002-rag-reliability-and-retrieval-quality-7784`

**Pull request**: #44, base `dev`

**First review**: 2 November 2026, 15:22 Europe/Paris, at `b2b4c34`, recorded a NO-GO. This update records the fixes for that NO-GO.

**Left untouched**: `infra/dev/release-gate.json` promotion switches and `rollback_digests`, the serving digests, image builds, DEV workflow dispatch, and merge of pull request #44. `rollback_in_effect` remains `false`. T030 stays unchecked.

## Recommendation

**NO-GO** for merging pull request #44, for promoting an image, for changing a running DEV digest, and for dispatching DEV acceptance.

The Feature 002 code requirements are implemented on this branch, with two limits that stay explicit: the lexical score is not a cosine, and SC-001's automated trial is one blocked sleep rather than three parser runs. T030 and the DEV browser journey are prepared and have not been executed. Image build dispatch did not start.

## Final requirement review

Reviewed 2 November 2026 against `spec.md` FR-001–FR-021, NFR-001–NFR-006, and SC-001–SC-009. Serving digests and `infra/dev/release-gate.json` were not edited. `rollback_in_effect` remains `false`. Promotion switches remain `false`.

| Requirement | Result |
| --- | --- |
| FR-001, FR-003, NFR-001 | Implemented. `/health/live` is served on the `worker-health` thread. Readiness stays on the ingestion loop. The probe timeout stays 5 seconds. |
| FR-002, SC-001 | The liveness mechanism is implemented. The automated trial is one `time.sleep(6)` with live probes, not three CPU-heavy parser runs. |
| FR-004, FR-020, NFR-005 | Implemented. The upload session, direct object write, and isolated parser stay. No second queue, no Celery path, and no new Alembic revision. |
| FR-005, FR-006, FR-007, SC-002, NFR-002 | Implemented. Citations keep the stored page range. The four-page parent is not collapsed to page 1. |
| FR-008, FR-009, FR-010, SC-003, NFR-003 | Implemented for assigned retriever scores. Nested fusion keeps `source_score_*` and puts the rank contribution on `score` and `rrf`. The floor runs before parent and neighbor expansion. Search and the pinned answer return `selection_has_no_supporting_evidence` when nothing remains. |
| FR-011, FR-012, FR-013, SC-004 | Implemented. Vector, lexical, and structural reads stay inside the tenant and the selected documents. A path request returns a `structural` or `entity` path, or one of `graph_not_stored`, `graph_no_entity_match`, or `graph_no_structural_path`. |
| FR-014, FR-015, FR-016, SC-005 | Implemented. A skip does not set the run warning. `semantic_graph_failed` is on the graph stage. Community summarization stays skipped. |
| FR-017, FR-018, SC-006 | The browser spec and fail-closed DEV target are implemented. The DEV upload has not been run. |
| FR-019, SC-007 | Local release-identity and heredoc checks pass. The acceptance workflow's last step is the product-check pytest and it does not promote. T030 is prepared below and is not executed. |
| FR-021, SC-009, NFR-006 | Implemented. The heartbeat uses a separate session, is capped at 60 seconds, and a persist error does not leave a finished run unacknowledged. |
| SC-008 | Not releasable. SC-006 has not been run, and no image from this feature is serving. |

## Lexical-score limitation

This limitation stays open and is not a reason to change the 0.12 floor in this phase. `InMemoryLexicalSearchStore` ranks with a term-frequency score. Hybrid fusion stores that score as a qualification score. A passage whose dense score is below 0.12 can still pass the floor when the lexical score is at least 0.12. The regression tests assign both scores, so they do not measure a live lexical index. `quickstart.md` records the same limit.

## Image build and scan

The existing workflows are `build-and-push-api-image.yml` (id 333154082), `build-and-push-worker-image.yml` (id 336482825), and `build-and-push-web-image.yml` (id 333154081). Each is `active`, defines `workflow_dispatch` with no branch filter, builds, pushes a tag equal to the commit SHA, and runs Trivy at CRITICAL and HIGH. The same files exist on `main` and on this feature branch. A dispatch with `--ref cursor/002-rag-reliability-and-retrieval-quality-7784` is a valid target. The GitOps job runs only when `github.ref` is `refs/heads/dev`. On `dev`, `check-release-gate.sh` still reads `promote.<component> == false`, so a closed gate does not write `infra/k8s`.

Dispatch was not started. A request with an empty body, which cannot create a run, was refused before GitHub validated the payload:

```text
HTTP 403: Resource not accessible by integration
X-Accepted-Github-Permissions: actions=write
POST /repos/coumarane/GraphRAG/actions/workflows/build-and-push-api-image.yml/dispatches
```

The caller is the cloud-agent GitHub App installation token (`ghs_`, account `cursor`). That token can read workflows and list runs. It cannot write Actions. The public Cursor GitHub App requests `actions: write`, and Cursor mints the cloud-agent token with Actions read only, so approving the app installation does not give this token write access. No other GitHub token is present in this environment. Repository Actions settings were not changed. The settings endpoint itself requires `administration: read`, which this token also lacks. Recent image builds on `dev` are `push` events, so the workflows run when a permitted caller starts them.

No API, worker, or web image was built for this feature. No new digest exists. The running DEV digests are unchanged:

| Component | Serving digest |
| --- | --- |
| API | `sha256:5abf5b69c59e7f1607d99ca87bfb6c7ff2e7ac26d28a57c644a3e6d2f06711a2` |
| Worker | `sha256:17eb0f6f6b57e218ae4d69ec568ece20c1e4573e2057806c0cb0cd56d6f4f1ea` |
| Web | `sha256:eb34e619be4107352fbb0ce3e543e8b368865059746060809589afe6d290dc84` |

The identity that runs these commands needs `actions: write` on `coumarane/GraphRAG`. Leave `image_tag` empty and `rebuild_base` false. They build and scan. They do not promote, because the ref is not `dev` and the gate is closed:

```bash
gh workflow run build-and-push-api-image.yml --ref cursor/002-rag-reliability-and-retrieval-quality-7784
gh workflow run build-and-push-worker-image.yml --ref cursor/002-rag-reliability-and-retrieval-quality-7784 -f rebuild_base=false
gh workflow run build-and-push-web-image.yml --ref cursor/002-rag-reliability-and-retrieval-quality-7784
```

## T030 and browser acceptance, prepared and not executed

T030 stays unchecked. The workflow file was not copied onto `origin/main` and `accept-dev-feature-002` was not dispatched.

The workflow now has a `git_ref` input. A later dispatch checks out that ref, generates the four-page PDF, and runs the product checks, including the nested-fusion test. A pull request run checks out the pull request. The job does not promote.

`cursor/t030-accept-workflow-only-7784` contains only that workflow file on top of `origin/main`. It is not merged and it has no pull request. Merging it, or dispatching it, waits for approval.

The DEV browser command in `quickstart.md` is the prepared acceptance command. It was not run.

## Score propagation

Reciprocal-rank fusion now keeps two kinds of score:

- Ranking scores are `score`, `rrf`, and `rrf_list_*`. A single rank-1 contribution is `1/61`, about 0.01639.
- Qualification scores are `source_score_*`. They are the original retriever scores. A later fusion copies those values and does not replace them with the rank contribution.

`retriever_score` still reads `source_score_*` when those keys exist. The 0.12 floor therefore compares the original retriever score after one fusion and after a second fusion.

`test_nested_rrf_preserves_a_retriever_score_of_0_80` fuses a dense score of 0.80, checks that the rank score is about 0.01639, fuses that result with another list, and checks that the qualification score is still 0.80. A retriever score of 0.05 stays 0.05 after the same nesting and remains below the floor.

## Query regression

`test_query_modes_keep_0_80_and_drop_below_floor_evidence` runs four requests through `RetrieveEvidenceService` with assigned vector and lexical scores:

| Case | Question | Modes |
| --- | --- | --- |
| factual | Where is the packing note kept? | naive, hybrid |
| assay | What is the assay specification for heavy metals? | hybrid, multimodal, naive |
| multimodal | What does the chart show? | naive, multimodal, hybrid |
| mix | Where is the packing note kept? | local, global, naive, multimodal, hybrid |

For each case the passage scored 0.80 is returned, its qualification score stays 0.80, and its rank component is not 0.80. The passage scored 0.05 is absent. Its parent and its page-adjacent neighbor are absent, so expansion does not restore a passage the floor already rejected. A second document scored 0.99 is absent when `document_ids` selects the first document. A second tenant receives an empty list and `selection_has_no_supporting_evidence`.

## Heartbeat failure

`_heartbeat_loop` logs `ingestion_heartbeat_persist_failed` and keeps sleeping after a persist error. The in-memory heartbeat moves only after the write returns. `_stop_heartbeat` cancels the task and swallows a persist exception, so `process_one` still reaches acknowledge or dead-letter.

`test_heartbeat_persist_failure_still_acks_the_finished_run` raises on every heartbeat write. The loop records at least two failures while the pipeline runs, the finished run is acknowledged, and the in-memory queue depth returns to zero.

## Redis CI

`.github/workflows/validate-feature.yml` job `backend-redis` starts `redis:7-alpine` published on `127.0.0.1:6380` and runs:

- `tests/integration/test_worker_crash_recovery.py`
- `tests/integration/test_outbox_restart.py`

The tests still use `compose_redis`. They skip when that port is closed. They are not replaced with mocks.

On 2 November 2026 a local `redis-server` answered `PONG` on port 6380. `uv run pytest tests/evaluation tests/integration -q -rs` then passed both Redis tests. Seven other integration tests still skipped because Postgres, MinIO, and Azurite were not listening. Those seven are Feature 001 service checks and are not new Feature 002 blockers.

GitHub Actions run [41471435896](https://github.com/coumarane/GraphRAG/actions/runs/41471435896) finished success at 16:28 Europe/Paris. The job `Redis integration tests` passed against the workflow's Redis service, together with the unit and frontend jobs.

## Corpus paths

The corpus stays in `data/evaluation/corpus`. References that still named `evaluation/corpus` now point there:

- `backend/scripts/generate_rag_challenge.py`
- `backend/tests/unit/test_pdf_line_splitting.py`, resolved from the test file
- `data/reports/rag-reliability-report.md`
- `data/reports/parser-comparison-eval-corpus.json`

`default_corpus_dir` and `docs/evaluation.md` already used `data/evaluation`.

## Checks

Recorded 2 November 2026, 16:24 Europe/Paris.

| Check | Result |
| --- | --- |
| `uv run pytest tests/unit -q` | 627 passed |
| `uv run pytest tests/evaluation tests/integration -q -rs` | 30 passed, 7 skipped. Redis crash-recovery and outbox republish passed |
| Frontend `npx tsc --noEmit` and `npx vitest run` | `tsc` passed. 5 files, 17 tests passed |
| Changed-file `ruff format` and `ruff check` | Passed |
| Pull request #44 at `4363753` | Green at 18:31 Europe/Paris. [Validate feature SHA](https://github.com/coumarane/GraphRAG/actions/runs/41491441563): backend unit tests, Redis integration tests, and frontend typecheck and tests passed. [Accept Feature 002](https://github.com/coumarane/GraphRAG/actions/runs/41491441534): product check passed. |

## Remaining blockers

| Blocker | Why it stays open |
| --- | --- |
| Image digests | Dispatch needs `actions: write`. This cloud-agent token is Actions read-only, so no API, worker, or web digest was produced. |
| T030 | Prepared on `cursor/t030-accept-workflow-only-7784`. Not merged to the default branch and not dispatched. |
| Live DEV browser acceptance | The command is documented. It has not been run. Today's web digest is not this feature's image. |
| SC-008 | The feature is not releasable while SC-006 is open and no feature image is serving. |

## Remaining technical debt

- Lexical retriever scores are not 0–1 cosines. A hybrid qualification score can clear 0.12 from the lexical score while the dense score is below the floor. The new tests assign both scores, so they do not measure a live lexical scale.
- SC-001 is evidenced by one blocked sleep on the ingestion loop, not by three parser invocations.
- Vision enrichment still writes the full run through the pipeline session.
- Full `ruff check .` and `mypy src` baselines were 179 findings and 156 errors at the 15:22 review. This pass did not mass-fix them.
- The seven Postgres, MinIO, and Azurite integration tests are not in CI.

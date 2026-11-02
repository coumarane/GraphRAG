# Implementation review: RAG Reliability and Retrieval Quality

**Updated**: 2 November 2026, 16:24 Europe/Paris

**Branch**: `cursor/002-rag-reliability-and-retrieval-quality-7784`

**Pull request**: #44, base `dev`

**First review**: 2 November 2026, 15:22 Europe/Paris, at `b2b4c34`, recorded a NO-GO. This update records the fixes for that NO-GO.

**Left untouched**: `infra/dev/release-gate.json` promotion switches and `rollback_digests`, the serving digests, image builds, DEV workflow dispatch, and merge of pull request #44. `rollback_in_effect` remains `false`. T030 stays unchecked.

## Recommendation

**NO-GO** for merging pull request #44, building an image, promoting a digest, or dispatching a DEV workflow.

The nested-fusion score bug, the heartbeat persist failure, and the missing Redis CI job are fixed. Two acceptance items stay open because their prerequisites are not met:

- T030. `.github/workflows/accept-dev-feature-002.yml` is on this branch only. It has not been dispatched and it is not on the default branch.
- Live DEV browser acceptance (FR-017, SC-006). The journey fails closed without DEV address and credentials. It has not been run. The serving web digest is not this feature's web image.

SC-008 stays failed while those two items are open.

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

## Remaining blockers

| Blocker | Why it stays open |
| --- | --- |
| T030 | The acceptance workflow has not been copied to the default branch and has not been dispatched. Copying it is a later workflow-only change. |
| Live DEV browser acceptance | FR-017 and SC-006 run after this feature's web image is deployed. Today's serving web digest `sha256:eb34e619be4107352fbb0ce3e543e8b368865059746060809589afe6d290dc84` is not that image. |
| SC-008 | The feature is not releasable while SC-006 is open. |

## Remaining technical debt

- Lexical retriever scores are not 0–1 cosines. A hybrid qualification score can clear 0.12 from the lexical score while the dense score is below the floor. The new tests assign both scores, so they do not measure a live lexical scale.
- SC-001 is evidenced by one blocked sleep on the ingestion loop, not by three parser invocations.
- Vision enrichment still writes the full run through the pipeline session.
- Full `ruff check .` and `mypy src` baselines were 179 findings and 156 errors at the 15:22 review. This pass did not mass-fix them.
- The seven Postgres, MinIO, and Azurite integration tests are not in CI.

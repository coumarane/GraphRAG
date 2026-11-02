# Pre-implementation analysis: RAG Reliability and Retrieval Quality

**Date**: 2026-11-02

**Feature**: [spec.md](../spec.md)

**Pull request**: #44, branch `cursor/002-rag-reliability-and-retrieval-quality-7784`, base `dev`

**Method**: The Spec Kit analyze skill file is not in this workspace. This pass compares `spec.md`, `plan.md`, `research.md`, `data-model.md`, `quickstart.md`, `tasks.md`, and the contracts with the current application code and with the Feature 001 DEV acceptance record. Critical and high findings were corrected in those artifacts. No application code, kustomization, release gate, or deployment was changed.

## Recommendation

**GO** for implementation of the revised specification on this branch.

**NO-GO** for merging pull request #44.

**NO-GO** for any image build, promotion, or DEV deploy.

Implementation has not started. Tasks T001–T035 remain open.

## Critical

| Finding | Why it was wrong | Resolution |
| --- | --- | --- |
| Liveness was specified as "do not take the ingestion lock." | `/health/live` is an asyncio callback on the ingestion loop. `db_lock` is held around `process_one`, but a lock held across an await does not stop that callback. `run_callable_isolated` already waits on a child process from a worker thread. An await-under-lock test would pass today and miss the timeout. The 11:44 Europe/Paris restart means the loop was not scheduling the probe. | FR-001, SC-001, T003, and T004 require an acceptor that is not the ingestion loop, proved by synchronous work longer than 5 seconds. The 5-second probe timeout stays. |
| A missing distinctive phrase was a universal no-evidence rule. | Search returns nearest neighbors with no floor. The answer floor is 0.12 on the retriever score and blocks only an already-empty list. The DEV toner hit's score was not recorded. `PageTwoCeramideAnchor` is not an exact token. A verbatim rule would reject a valid paraphrase. Reciprocal-rank fusion replaces `score` with about 0.016 for rank 1, so applying 0.12 to that score would empty every fused result. Expansion after the floor would let a below-floor child become a parent that looks kept. | FR-008, FR-009, FR-010, and SC-003 apply 0.12 to the retriever score before parent or neighbor expansion. Tests assign scores. An above-floor passage may omit a verbatim copy. |

## High

| Finding | Resolution |
| --- | --- |
| The in-memory heartbeat is not persisted. Member progress stalls after 120 seconds and reclaim uses 90 seconds, so a long parse looks dead while the worker is alive. A concurrent write on the pipeline session is unsafe. | FR-021 and SC-009. T034 persists `heartbeat_at` at least every 60 seconds from a separate session. No new table. |
| A probe kill and an operator stop are both SIGTERM. The process cannot tell them apart after the fact. | FR-003. A healthy parse must not need the kill. Operator stop stays a clean exit. |
| `semantic_graph_failed` is appended to raw warnings while the graph step still returns completed. A skip-only warning rule would hide it if finalize does not copy that text. | FR-015 and T035. The graph step is `completed_with_warnings`. Step status is authoritative. Prefixes are examples, not a closed list. |
| A structural neighborhood that is only tenant-scoped can follow a shared entity into another document. | FR-012 and T016. Paths and supporting passages stay inside the selected documents. `test_local_graph_retrieval_respects_document_scope` and `test_local_graph_retrieval_returns_mentioned_chunks` stay green. |
| The browser journey was specified against today's DEV web image. That image was not built from this feature. A hosted-runner API call and a hand-built PDF are not the journey. | FR-017 and SC-006. The journey runs after this feature's web image is deployed. Missing credentials fail closed. Cloudflare 1010 fails the job. |
| A heredoc scan of this branch cannot see `accept-dev-feature-001.yml`, which lives on the default branch. The historical failure was a `CHK` block closed with `PY` after the product checks had printed success. | SC-007 and T028 include a fixture of that mismatched closer. Copying the new workflow to the default branch is T030, later, and is not a feature merge or a promotion. |
| Serving digests and rollback digests were easy to treat as one identity. Equality is valid only during an explicit rollback. A test that hardcodes today's serving digest breaks on the next promotion. | FR-019. `rollback_in_effect` is additive and stays false. T027 adds it later without changing `promote` or `rollback_digests`. This review does not edit the gate file. |
| FR-001 through FR-020 and SC-001 through SC-008 were not all mapped to tasks. | The coverage table in `tasks.md` maps FR-001–FR-021 and SC-001–SC-009. |

## Medium, left open

These do not block implementation.

- A multipage parent citation's element identifier may still be the first element. The page range is the member-facing fix. Element-level highlighting stays out of scope.
- Neighbor expansion may return an adjacent page. That hit is valid when its own page range matches its text.
- The 11:44 Europe/Paris restart is not proven to be synchronous CPU, the GIL, or another stall. The required behavior covers a blocked loop either way.
- The live cosine of the toner and serum pair was not captured. Tests inject scores. Evaluation movement is unknown until those tests run.
- Skip-only runs change from `completed_with_warnings` to `completed`, and `latest_warning` becomes empty. Feature 001's acceptance check accepts both statuses. A client that matches the exact text "community summarization disabled" will see empty. The field remains. Community summarization stays disabled.
- Removing the three-page citation collapse changes answer page ranges. Search already returned the stored range.
- Copying `accept-dev-feature-002.yml` onto the default branch is an implementation step after review. Repository dispatch reads workflow YAML from that branch.
- The public browser journey cannot pass on the web digest serving on 2 November 2026. That is expected.

## Coverage

The task table maps every functional requirement and success criterion. No requirement is left without a test task and an implementation task, except the process gate SC-008, which maps to the release tasks and the local quality commands.

## What this pass did not do

- No application change, merge, image build, or deploy.
- No edit of `infra/dev/release-gate.json` or of the kustomize digests.
- No new Alembic revision.
- No change to parser library versions, worker replica count, or the Redis stream contract.

# Research: RAG Reliability and Retrieval Quality

## Decision: Answer liveness off the ingestion event loop

**Decision**: Serve `/health/live` from an acceptor that is not the ingestion event loop. Keep `/health/ready` on that loop as the dependency check. Keep the Kubernetes timeout at 5 seconds. Keep `run_callable_isolated` as the parser child. Do not treat "skip `db_lock`" as the fix.

**Rationale**: `backend/src/graph_rag/infrastructure/workers/main.py` accepts liveness on the same asyncio server as the loop that runs `worker.process_one`. The loop holds `db_lock` around that call. A lock held across an await does not stop the health callback, so an await-under-lock test passes today and misses the defect. `run_callable_isolated` already uses `subprocess.Popen` inside `asyncio.to_thread`, so a healthy isolated parse awaits and should not block the loop by itself. The 5-second timeout means the loop was not scheduling the probe. Synchronous pipeline work on that loop can do that while the lock is also held. `infra/k8s/worker/deployment.yaml` uses a 5-second liveness timeout, a 15-second period, and the default failure threshold. The process installs SIGTERM as a clean stop and logs `worker_stopped`. A probe kill and an operator stop are the same signal and are not distinguished after the fact. The 2 November 2026 DEV restart was `Completed` exit 0 at 11:44 Europe/Paris, caused by a liveness timeout, and the following three uploads did not restart that process. The filtered log does not prove whether that stall was synchronous CPU, the GIL, or another loop stall. The required behavior does not depend on which of those it was. A longer timeout would hide a stuck loop. A second worker framework is not required. The queue stays the Redis stream `ingestion-jobs` with group `ingestion-workers`.

**Alternatives considered**:

- Serve liveness on the same loop and only skip `db_lock`. Rejected. The callback still cannot run while that loop is blocked by synchronous work.
- Raise `timeoutSeconds` and `failureThreshold`. Rejected. A busy healthy worker would still be one blocked loop away from a restart, and a stuck loop would take longer to surface.
- Move parsing back into the parent process. Rejected. Feature 001 isolated the native library so a child SIGILL becomes exit 132 instead of killing the worker.
- Add Celery. Rejected. `application/admin/console.py` already reports Celery unused and names the Redis Streams worker.

## Decision: Persist the heartbeat from a separate session

**Decision**: While a stage runs, refresh the persisted run heartbeat at least every 60 seconds from a session that is not the pipeline `AsyncSession`. Do not write that heartbeat through the locked pipeline session.

**Rationale**: `_heartbeat_loop` updates the in-memory record about every 15 seconds and intentionally does not persist, because a concurrent write on the shared session corrupts the pipeline's next write. `_persist_progress` sets `heartbeat_at` at stage boundaries. `derive_progress_state` reports stalled after 120 seconds. Reclaim treats a heartbeat older than 90 seconds as stale. A PARSE longer than those windows looks dead while the worker is alive. A dedicated session is the fix already named in the worker comment. No new table and no Alembic revision.

**Alternatives considered**:

- Keep the in-memory heartbeat only. Rejected. Member progress and reclaim read the persisted value.
- Share the pipeline session under the existing lock. Rejected. That reintroduces the session race the comment forbids.
- Shorten the stall window. Rejected. A live long parse would still look stalled if the persisted stamp never moves.

## Decision: Keep the passage page range on the citation

**Decision**: Stop collapsing citations whose `page_end - page_start >= 3` onto `page_start`. Search evidence and query citations use the passage's stored `page_start` and `page_end`.

**Rationale**: `HierarchicalChunker._make_section_parent` sets the parent range from the first and last element page. `_build_chunk` sets the child range from its own elements. `evidence_to_citation` in `domain/citations/registry.py` then rewrites a span of three or more pages to a single page. The accepted DEV parent covered pages 1–4, and the page-2 query citation was labeled pages 1–1 while the quoted text contained `PageTwoCeramideAnchor`. Search evidence for that child already said pages 2–2. The collapse is the defect. Parent text may still span pages; the citation must say so.

**Alternatives considered**:

- Split every parent into one page before indexing. Rejected as a new chunker. Children already exist per page, and the parent is a legitimate multi-page passage.
- Put the page only in the prompt text. Rejected. The API field is what the member and the tests read.

## Decision: One evidence floor for search and answers

**Decision**: Drop passages whose retriever score is below 0.12 before parent or neighbor expansion and before assembly. If none remain, return no evidence and `selection_has_no_supporting_evidence`. Compare 0.12 to the retriever score, not to a min-max of one list and not to a reciprocal-rank score. An above-floor passage may be returned without a verbatim copy of the question.

**Rationale**: `assess_evidence` already defaults `min_top_score` to 0.12 and emits `low_retrieval_score`. `HardInvariantGate.enforce_evidence_sufficiency` blocks a pinned query only when the evidence list is empty. `POST /api/v1/retrieval/search` returns `top_k` hits with no floor. `normalize_scores` maps a constant list, including a single score, to 1.0, and `apply_normalized_component` stores that beside the score. `reciprocal_rank_fusion` replaces `score` with `1/(k+rank)` at `k=60`, so rank 1 is about 0.016 and is always below 0.12. It keeps the original as `source_score_{list_index}`. Applying 0.12 to the fused score would reject every multi-branch result. Applying it after `expand_parents_and_neighbors` would let a below-floor child expand into a parent that looks kept. The DEV toner search for `PageTwoCeramideAnchor` returned the toner with the phrase absent. That numeric score was not recorded. `PageTwoCeramideAnchor` is not an exact token under `_looks_like_exact_token`, so the boost is not the missing filter. A universal verbatim-absence rule would reject a valid paraphrase. Tests assign scores and also assert the other document's sentence is absent.

**Alternatives considered**:

- Treat a missing distinctive phrase as no evidence even when a passage is above the floor. Rejected. That would break semantic matches. The defect is the missing floor.
- A new learned threshold. Rejected for this feature. The existing floor is the contract until evaluation moves it.
- Return the weak hit with a warning. Rejected. Feature 001 showed that a warning still looks like support when the passage is in the list.
- Apply 0.12 to the reciprocal-rank score. Rejected. Rank 1 is always below 0.12.

## Decision: Structural paths are graph retrieval

**Decision**: When the caller sets `include_graph_paths` and the selected documents have stored graph nodes, return a structural path across document, version, and passage nodes, or an entity path when entities resolve. Nodes and supporting passages belong only to those documents. Otherwise return exactly one of `graph_not_stored`, `graph_no_entity_match`, or `graph_no_structural_path`. A semantic failure sets the graph step to completed with warnings.

**Rationale**: `stage_extract_graph` completes after `StructuralGraphBuilder` or after a semantic build. Semantic failure appends `semantic_graph_failed` to the raw warning list, upserts the structural graph, and still returns completed, so the step itself has no warning. `_local` returns no path when `resolve_entities` is empty, and it falls back to dense search. `resolve_entities` matches `normalized_name` for the tenant. Structural nodes do not have to carry that name. The accepted searches asked for paths, finished `INDEX_GRAPH`, and received `graph_paths` 0 with no reason. Neo4j neighborhood queries already require `tenant_id` on the seed and the neighbor. A shared entity can still cross documents in the same tenant, so the selected `document_ids` filter is required. `test_local_graph_retrieval_respects_document_scope` already locks that boundary for entity retrieval and must stay green.

**Alternatives considered**:

- Treat empty paths as success whenever `INDEX_GRAPH` completed. Rejected. That is the current gap.
- Require entity extraction on every PDF. Rejected. It would turn an optional semantic failure into a blocked document, and short text PDFs may have no entities.
- Walk the structural neighborhood without a document filter. Rejected. Shared entity edges can leave the selected document.

## Decision: Skip reasons do not warn the run

**Decision**: `progress().latest_warning` and `_has_warning_stages` consider only stages whose status is `completed_with_warnings`. Skipped stages keep their reason on the stage record. Step status is authoritative. Warning prefixes are examples, not a closed allowlist. `stage_extract_graph` returns completed with warnings and the `semantic_graph_failed` text when semantic extraction fails.

**Rationale**: `mark_skipped` assigns the reason to `record.warning`. `_has_warning_stages` is true when the status is `completed_with_warnings` or the warning string is non-empty. `progress()` walks stages backward and takes the first warning, so `SUMMARIZE_COMMUNITIES` with "community summarization disabled" becomes the latest warning after finalize's warning is empty. The accepted runs had genuine warnings none and that latest warning. Stage status is already `skipped`. `test_happy_path_progress_and_finalize_gate` also sets a parse warning of "low ocr", so a skip-only case is not what that test locks. If the new rule ignores only skipped-stage warnings, a semantic failure that lives only on `raw.warnings` can be dropped when it is not the first copied warning. The graph step must carry it. `vision_failed={n}` and `document_intelligence: missing=...` stay genuine because their steps complete with warnings, even when the text is not in an example prefix list. Skip-only runs change from `completed_with_warnings` to `completed` with an empty `latest_warning`. Feature 001's acceptance check accepts both statuses. Clients that match the exact skip text will see empty instead. The field stays.

**Alternatives considered**:

- Classify warnings by a closed prefix list. Rejected. A genuine warning with other text, including a document-intelligence miss, would be hidden.
- Change the acceptance script to ignore the run status. Rejected. Members read `latest_warning` from the API (FR-013 of Feature 001).
- Enable community summarization. Rejected. The step is intentionally idle, and enabling it is a different feature.

## Decision: Generated PDFs and a reachable browser

**Decision**: Browser and retrieval fixtures generate PDFs with a standard library such as fpdf2. The DEV Playwright target requires `E2E_BASE_URL` and credentials from the environment. A missing value fails. A runner that cannot open the origin fails. Hand-built PDF 1.4 bodies are not page-citation fixtures.

**Rationale**: `frontend/e2e/upload-journey.spec.ts` builds a one-page PDF by concatenating objects and defaults to `admin@example.com` / `change-me-now-12` on `http://localhost:3010`. Playwright has no workflow. The public API from a GitHub-hosted runner returned Cloudflare 1010. Run 41432009049 showed Docling mis-paging a hand-built file. Run 41433025148 showed fpdf2 pages 1–4 mapping correctly, from inside an API pod rather than a browser.

**Alternatives considered**:

- Call the in-cluster API and name it a browser test. Rejected. Feature 001 already has that API proof.
- Commit DEV credentials. Rejected by the constitution.

## Decision: Serving digests and rollback digests are different fields

**Decision**: Kustomize `images[].digest` is the serving identity. `infra/dev/release-gate.json` `rollback_digests` is the rollback identity. Add `rollback_in_effect`, default false. A promotion updates serving and moves the previous serving digest into `rollback_digests`. Equality is valid only when `rollback_in_effect` is true. The acceptance workflow's exit status is the product-check status, and a unit test checks that Python heredoc closers match their openers.

**Rationale**: On 2 November 2026 the serving digests were API `sha256:5abf5b69c59e7f1607d99ca87bfb6c7ff2e7ac26d28a57c644a3e6d2f06711a2`, worker `sha256:17eb0f6f6b57e218ae4d69ec568ece20c1e4573e2057806c0cb0cd56d6f4f1ea`, and web `sha256:eb34e619be4107352fbb0ce3e543e8b368865059746060809589afe6d290dc84`. The gate still holds the older rollback digests and closed promotion switches. `test_release_gate_stays_closed_and_records_rollback_digests` reads the promote and rollback dicts, so an extra `rollback_in_effect` field does not break it. This specification does not edit the gate file. Adding the field is task T027 and must not change those dicts. A test that hardcodes today's serving digest as a permanent expected value would break on the next promotion. Compare inequality while `rollback_in_effect` is false. Acceptance run 41433025148 printed `acceptance_documents true` and `worker_stable true`, then `NameError: name 'PY' is not defined` because a `CHK` heredoc was closed with `PY`. That closer is fixed on the default branch in `845c6ef`. `accept-dev-feature-001.yml` is not on this branch. A scan of `.github/workflows/*.yml` here cannot see the historical bug, so the unit test includes a fixture of that mismatched closer. Copying the Feature 002 workflow onto the default branch is a later workflow-only change.

**Alternatives considered**:

- Force kustomize back to the rollback digests. Rejected. That would redeploy Feature 001's predecessors and violate the accepted DEV state.
- Open the promotion switches in this specification. Rejected. Review comes before any deploy.

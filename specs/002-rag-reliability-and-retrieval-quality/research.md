# Research: RAG Reliability and Retrieval Quality

## Decision: Answer liveness outside the ingestion lock

**Decision**: Serve `/health/live` from the worker process without taking `db_lock` and without waiting on `process_one`. Keep `/health/ready` as the dependency check. Keep the Kubernetes timeout at 5 seconds. Keep `run_callable_isolated` as the parser child.

**Rationale**: `backend/src/graph_rag/infrastructure/workers/main.py` accepts liveness on the same asyncio server as the loop that holds `db_lock` around `worker.process_one`. `infra/k8s/worker/deployment.yaml` uses a 5-second liveness timeout, a 15-second period, and the default failure threshold. The process installs SIGTERM as a clean stop and logs `worker_stopped`. The 2 November 2026 DEV restart was `Completed` exit 0 at 11:44 Europe/Paris, caused by a liveness timeout, and the following three uploads did not restart that process. A longer timeout would hide a stuck loop. A second worker framework is not required.

**Alternatives considered**:

- Raise `timeoutSeconds` and `failureThreshold`. Rejected. A busy healthy worker would still be one blocked loop away from a restart, and a stuck loop would take longer to surface.
- Move parsing back into the parent process. Rejected. Feature 001 isolated the native library so a child SIGILL becomes exit 132 instead of killing the worker.
- Add Celery. Rejected. `application/admin/console.py` already reports Celery unused and names the Redis Streams worker.

## Decision: Keep the passage page range on the citation

**Decision**: Stop collapsing citations whose `page_end - page_start >= 3` onto `page_start`. Search evidence and query citations use the passage's stored `page_start` and `page_end`.

**Rationale**: `HierarchicalChunker._make_section_parent` sets the parent range from the first and last element page. `_build_chunk` sets the child range from its own elements. `evidence_to_citation` in `domain/citations/registry.py` then rewrites a span of three or more pages to a single page. The accepted DEV parent covered pages 1–4, and the page-2 query citation was labeled pages 1–1 while the quoted text contained `PageTwoCeramideAnchor`. Search evidence for that child already said pages 2–2. The collapse is the defect. Parent text may still span pages; the citation must say so.

**Alternatives considered**:

- Split every parent into one page before indexing. Rejected as a new chunker. Children already exist per page, and the parent is a legitimate multi-page passage.
- Put the page only in the prompt text. Rejected. The API field is what the member and the tests read.

## Decision: One evidence floor for search and answers

**Decision**: Drop retrieved passages whose retrieval score is below 0.12 before assembly. If a pinned question's distinctive phrase occurs in none of the selected passages, return no evidence. Compare 0.12 to the retrieval score, not to a min-max of one list and not to a reciprocal-rank score.

**Rationale**: `assess_evidence` already defaults `min_top_score` to 0.12 and emits `low_retrieval_score`. `HardInvariantGate.enforce_evidence_sufficiency` blocks a pinned query only when the evidence list is empty. `POST /api/v1/retrieval/search` returns `top_k` hits with no floor. `normalize_scores` maps a constant list, including a single score, to 1.0, and `apply_normalized_component` stores that beside the score. The DEV toner search for `PageTwoCeramideAnchor` returned the toner with the phrase absent. Phrase absence is decidable without knowing that sample's cosine.

**Alternatives considered**:

- A new learned threshold. Rejected for this feature. The existing floor is the contract until evaluation moves it.
- Return the weak hit with a warning. Rejected. Feature 001 showed that a warning still looks like support when the passage is in the list.

## Decision: Structural paths are graph retrieval

**Decision**: When the caller sets `include_graph_paths` and the document has stored graph nodes, return a structural path across document, version, and passage nodes, or an entity path when entities resolve. Otherwise return one of `graph_not_stored`, `graph_no_entity_match`, or `graph_no_structural_path`.

**Rationale**: `stage_extract_graph` completes after `StructuralGraphBuilder` or after a semantic build. Semantic failure appends `semantic_graph_failed` and still upserts the structural graph. `_local` returns no path when `resolve_entities` is empty, and it falls back to dense search. `resolve_entities` matches `normalized_name` for the tenant. Structural nodes do not have to carry that name. The accepted searches asked for paths, finished `INDEX_GRAPH`, and received `graph_paths` 0 with no reason. Neo4j queries already require `tenant_id`.

**Alternatives considered**:

- Treat empty paths as success whenever `INDEX_GRAPH` completed. Rejected. That is the current gap.
- Require entity extraction on every PDF. Rejected. It would turn an optional semantic failure into a blocked document, and short text PDFs may have no entities.

## Decision: Skip reasons do not warn the run

**Decision**: `progress().latest_warning` and `_has_warning_stages` consider only stages whose status is `completed_with_warnings`. Skipped stages keep their reason on the stage record.

**Rationale**: `mark_skipped` assigns the reason to `record.warning`. `_has_warning_stages` is true when the status is `completed_with_warnings` or the warning string is non-empty. `progress()` walks stages backward and takes the first warning, so `SUMMARIZE_COMMUNITIES` with "community summarization disabled" becomes the latest warning. The accepted runs had genuine warnings none and that latest warning. Stage status is already `skipped`. `test_happy_path_progress_and_finalize_gate` also sets a parse warning of "low ocr", so a skip-only case is not what that test locks.

**Alternatives considered**:

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

**Rationale**: On 2 November 2026 the serving digests were API `sha256:5abf5b69c59e7f1607d99ca87bfb6c7ff2e7ac26d28a57c644a3e6d2f06711a2`, worker `sha256:17eb0f6f6b57e218ae4d69ec568ece20c1e4573e2057806c0cb0cd56d6f4f1ea`, and web `sha256:eb34e619be4107352fbb0ce3e543e8b368865059746060809589afe6d290dc84`. The gate still holds the older rollback digests and closed promotion switches. `test_release_gate_stays_closed_and_records_rollback_digests` reads only the gate. Acceptance run 41433025148 printed `acceptance_documents true` and `worker_stable true`, then `NameError: name 'PY' is not defined` because a `CHK` heredoc was closed with `PY`. That closer is fixed on the default branch in `845c6ef` and is not yet guarded in this branch.

**Alternatives considered**:

- Force kustomize back to the rollback digests. Rejected. That would redeploy Feature 001's predecessors and violate the accepted DEV state.
- Open the promotion switches in this specification. Rejected. Review comes before any deploy.

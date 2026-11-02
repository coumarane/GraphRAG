# Feature 001 acceptance on DEV

**Date**: 2 November 2026

**Status**: Accepted on the existing OVH DEV deployment, with the limitations in section 5.

This review did not rebuild an image, change a kustomization digest, or dispatch a promotion. The architecture, schema, and release gate are unchanged. Alembic head remains `0013_upload_sessions`. `promote.api`, `promote.worker`, and `promote.web` remain false.

## Verdict

The three P0 defects are closed in the deployed API and worker, and their regression tests are on `dev` in commit `fd3a04aa3f7ac667dbdc98e59c0154408077e0da`.

One four-page cosmetics PDF and two companion documents went through upload, Docling parsing, chunking, vector indexing, graph indexing, and retrieval. Page-level citations and document filters held. The worker stayed Ready across those three uploads. Redis pending and the Redis dead-letter stream stayed empty. Argo CD stayed Synced and Healthy on the digests already deployed.

## 1. P0 defects

| Defect | Cause | Deployed fix | Regression tests |
|---|---|---|---|
| Worker exit 132 | Multiprocessing spawn still fork-execs. After PDFium or OpenMP is loaded, `pthread_atfork` raises SIGILL in the parent. `except Exception` does not catch it, so the container dies and Redis redelivers the job. | The parent starts `graph_rag.infrastructure.parsers.isolate_main` with `subprocess.Popen`, which uses `posix_spawn` and does not run the parent's atfork handlers. A child return code of -4 becomes `ParserError` with `exit_code` 132. `ParserError` is not retried. | `test_sigill_in_parser_child_becomes_exit_132`, `test_parser_error_in_child_stays_a_parser_error`, `test_isolated_parser_returns_its_result`, `test_reindex_is_not_a_parser_name` in `backend/tests/unit/test_native_parser_isolation.py` |
| Search HTTP 500 | `PostgresQuotaService.reserve` is async. The route used the returned coroutine as a reservation, so `reservation.reservation_id` raised `AttributeError` after a successful retrieve. Empty and multi-evidence searches both failed, and the error handler raised it again on release. | The search, authorization, and MCP callers await the reservation when the result is awaitable. | `test_async_quota_search_returns_zero_and_multiple_sources` and `test_vector_search_hides_other_tenant_chunks` in `backend/tests/unit/test_retrieval_search_http.py` |
| Upload session not found | `create_upload_session` flushed and returned the presigned URL without `commit_db()`. The Azure PUT then succeeded, and complete or status on the other API replica returned 404. A later 409 for the same bytes is the existing duplicate-content check. | Create commits the session before it returns the upload URL. | `test_other_replica_completes_after_azure_put` in `backend/tests/unit/test_upload_session_replica_visibility.py`. Browser sequence: `frontend/e2e/upload-session-found.spec.ts`, "Azure PUT is followed by complete for the same upload session". |

The search and upload fixes are in API image `eefe37c52080920bbc5a597ecc76ca23e9566c1c`, digest `sha256:5abf5b69c59e7f1607d99ca87bfb6c7ff2e7ac26d28a57c644a3e6d2f06711a2`, written to GitOps by `733ab872ce4352b5820e55dbaa59f1262daeb124`. Promotion run: `https://github.com/coumarane/GraphRAG/actions/runs/41420039711`.

The worker isolation fix is `7201164fd1ee16f15b04b23ee1bda0baf96ba225`, digest `sha256:17eb0f6f6b57e218ae4d69ec568ece20c1e4573e2057806c0cb0cd56d6f4f1ea`, written to GitOps by `92745e44bde170c44c396fd4e06c3a1cb32541e1`. Image build: `https://github.com/coumarane/GraphRAG/actions/runs/41423951663`. Promotion run: `https://github.com/coumarane/GraphRAG/actions/runs/41425542537`.

The web digest was not part of these promotions. The Playwright upload regression is committed. The deployed web image is unchanged.

## 2. Multipage DEV evidence

Workflow `Accept Feature 001 DEV`, run `https://github.com/coumarane/GraphRAG/actions/runs/41433025148`, workflow SHA `3669ba74c4fc4b2ff3c16fdad355e2d1947d0616`. The run started at 11:58 Europe/Paris (10:58 UTC) and printed its product result at 12:02 Europe/Paris (11:02 UTC).

The upload ran inside a Ready API pod against `http://127.0.0.1:8000`. A direct call from the GitHub runner to `https://api.chatwithdocs.org` is rejected by Cloudflare error 1010, which is not a product defect. The PDFs were generated with fpdf2 on the runner and passed into the pod. Each upload used the product path: create, PUT to the returned Azure staging URL, then complete.

| Document | Id | Bytes | Pages | Create | PUT | Complete | Result |
|---|---|---|---|---|---|---|---|
| `citrine-serum-41433025148` | `01a19be9-c37a-759c-8253-e65503ba4742` | 2494 | 4 | 201 | 201 | 202 | `ready`, Docling, 4 pages |
| `willow-toner-41433025148` | `01a19be9-cbd9-7797-bec3-3283932acc8b` | 1067 | 1 | 201 | 201 | 202 | `ready`, Docling, 1 page |
| `stability-balm-41433025148` | `01a19be9-d323-7e15-bc7b-09699e3a41bc` | 1056 | 1 | 201 | 201 | 202 | `ready`, Docling, 1 page |

Each PUT host was `graphragdocsdevbmo9.blob.core.windows.net`. Each key contained `/uploads/` and `/staging/`.

Serum finished first, at about 12:00 Europe/Paris. Toner and balm finished by 12:02 Europe/Paris. The worker processed them one after another. All three runs finished `completed_with_warnings`. For the serum, `PARSE`, `CHUNK`, `EMBED`, `INDEX_VECTOR`, `INDEX_GRAPH`, and `FINALIZE` were `completed`. `EXTRACT_GRAPH` was also `completed`. The same completed core stages were present on the toner and the balm.

Serum chunks, five in total:

| Pages | Anchor |
|---|---|
| 1–1 | `PageOneNiacinamideAnchor` |
| 1–4 | all four page anchors |
| 2–2 | `PageTwoCeramideAnchor` |
| 3–3 | `PageThreeClaimAnchor` |
| 4–4 | `PageFourUsageAnchor` |

Retrieval, all HTTP 200, `graph_paths` 0:

- `PageTwoCeramideAnchor` limited to the serum returned only that document. Evidence and a query citation covered pages 2–2 and contained the phrase.
- `PageFourUsageAnchor` limited to the serum returned only that document. Evidence and the only query citation covered pages 4–4 and contained the phrase.
- `IsolatePhraseWillowBark` limited to the serum returned only the serum, and the phrase was absent.
- The same phrase limited to the toner returned only the toner, pages 1–1, phrase present.
- `PageTwoCeramideAnchor` limited to the toner returned only the toner, and the phrase was absent.
- `StabilityPhrasePetrolatum` limited to the balm returned only the balm, pages 1–1, phrase present.

An earlier one-page PDF on these same digests, document `01a19bcc-5666-7174-8c64-d751bfa710f7` (`citrine-002`), also reached `ready` through Docling, chunk, vector index, graph index, and a search citation for that document only. The multipage run above is the acceptance fixture.

## 3. Worker, Argo CD, and Redis

Read at 11:59 Europe/Paris, before the three uploads, and again at 12:02 Europe/Paris, after they were ready.

| Check | Before | After |
|---|---|---|
| Argo CD `chatwithdocs-api`, `chatwithdocs-web`, `chatwithdocs-worker` | Synced, Healthy, revision `92745e44bde170c44c396fd4e06c3a1cb32541e1` | Same |
| API | `sha256:5abf5b69c59e7f1607d99ca87bfb6c7ff2e7ac26d28a57c644a3e6d2f06711a2` | Same |
| Worker | `sha256:17eb0f6f6b57e218ae4d69ec568ece20c1e4573e2057806c0cb0cd56d6f4f1ea` | Same |
| Web | `sha256:eb34e619be4107352fbb0ce3e543e8b368865059746060809589afe6d290dc84` | Same |
| Pod `ingestion-worker-56cfd7f68b-p2vkp` | Ready, restarts 1, started 11:44 Europe/Paris (10:44:51 UTC) | Ready, restarts 1, same start time |
| Redis `ingestion-jobs` length | 9 | 12 |
| Redis `ingestion-dlq` length | 0 | 0 |
| Redis pending in `ingestion-workers` | 0, and 0 pending entries | 0, and 0 pending entries |

The stream grew by the three new jobs and was drained. The worker process that started at 11:44 Europe/Paris handled all three documents. That earlier restart was a liveness timeout on `/health/live`, recorded as `Completed` with exit 0 because the process traps SIGTERM. It happened before this batch and did not recur.

The GitHub job is marked failed. After printing `acceptance_documents true`, `worker_stable true`, `redis_pending_clear true`, and `redis_dlq_clear true`, the confirm script executed the token `PY` and raised `NameError`. The heredoc had been opened with `CHK`. That is a workflow terminator, not a product failure. The closer is corrected on `main` in `845c6ef13915ca90b6cc23df91d7ffc8269e6de5`. The upload was not repeated.

## 4. `completed_with_warnings`

All three runs reported `latest_warning` `community summarization disabled` and `genuine_warnings` none. `warnings_only_optional_skips` was true for each.

`mark_skipped` stores the skip reason in `record.warning`. `_has_warning_stages` treats any warning string as a run warning, and `progress()` walks stages in reverse and surfaces the latest warning. A skipped stage therefore makes the run `completed_with_warnings` even when the stage status is `skipped`. The stage list is the distinction.

On every acceptance document the skipped stages were:

| Stage | Status | Warning |
|---|---|---|
| `ENRICH_TABLES` | skipped | `handled in parse/vision/chunk` |
| `ENRICH_EQUATIONS` | skipped | `handled in parse/vision/chunk` |
| `BUILD_CONTEXT` | skipped | `handled in parse/vision/chunk` |
| `EXTRACT_DOCUMENT_INTELLIGENCE` | skipped | `document_intelligence not requested` |
| `RESOLVE_ENTITIES` | skipped | `handled in parse/vision/chunk` |
| `SUMMARIZE_COMMUNITIES` | skipped | `community summarization disabled` |

`ENRICH_IMAGES` completed with an empty warning. No stage was `completed_with_warnings`. No warning contained `semantic_graph_failed`, `vision_failed`, `needs_review`, `parser_fallback`, or `parser_routing`.

Read `stages[].status` together with the warning:

- `skipped`, and a warning containing `disabled`, `not requested`, `not configured`, or `handled in`, is an intentional optional skip.
- Stage status `completed_with_warnings`, or a warning containing `semantic_graph_failed`, `vision_failed`, `needs_review`, `parser_fallback`, or `parser_routing`, is a genuine enrichment or parse failure.
- Document status `partial` means the run needs review, which is a different outcome from a skipped optional stage.

## 5. Remaining limitations

1. Run status and `latest_warning` do not separate an intentional skip from a genuine enrichment failure. The stage list does. This review left that behavior in place. Changing it would require a worker image, and no blocking defect required one.
2. The worker restarted once at 11:44 Europe/Paris because `/health/live` timed out. The probe shares the worker asyncio loop. The three acceptance uploads did not restart it again. A long native-parser wait can still trip the probe. The trapped SIGTERM is recorded as exit 0, so the restart does not look like a crash.
3. `graph_paths` was 0 for these short text PDFs, while `INDEX_GRAPH` and `EXTRACT_GRAPH` completed. One serum chunk spans pages 1–4, so some hits are ranges. Page-exact chunks exist for pages 1, 2, 3, and 4, and the page-2 and page-4 queries each returned a page-exact citation. The page-2 query also returned a citation labeled pages 1–1 whose evidence still contained the page-2 phrase.
4. A search for the serum phrase limited to the toner returned the toner with the phrase absent. The serum text did not leak. The hit is a weak match inside the selected document.
5. The public browser upload was not driven in this review. The API path was. The deployed web digest is still `sha256:eb34e619be4107352fbb0ce3e543e8b368865059746060809589afe6d290dc84`.
6. A hand-built PDF 1.4 is not a valid page-citation fixture for Docling. Run `https://github.com/coumarane/GraphRAG/actions/runs/41432009049` placed the last page's text on page 3. The accepted fixture is the fpdf2 PDF in section 2.
7. The rollback digests in `infra/dev/release-gate.json` are not the images Argo CD is running. They remain the rollback target. The gate flags stay false, so a later push does not move the serving digests.
8. Community summarization, unrequested document intelligence, table and equation enrichment, context build, and entity resolution stay intentionally skipped on this path.

## 6. What stayed in place

- No image build and no promotion during this review.
- No database migration and no schema change.
- No change to row-level security.
- `pypdfium2`, torch, and Marker versions unchanged.
- Release-gate promote flags still false.

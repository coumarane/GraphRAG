# Feature 002 acceptance on DEV

**Date**: 4 November 2026, 09:27 Europe/Paris

**Status**: Accepted on the existing DEV deployment.

The release gate was not opened. `promote.api`, `promote.worker`, and `promote.web` stay false, and `rollback_in_effect` stays false. Alembic head remains `0013_upload_sessions`. No new infrastructure was added.

## Verdict

Feature 002 is accepted. The product check, the browser journey on https://chatwithdocs.org, and the in-cluster ingestion checks passed on the same run. API, worker, and web were Synced and Healthy on the digests below.

## Serving digests

Confirmed by Argo CD at 09:13 Europe/Paris (run [41797778132](https://github.com/coumarane/GraphRAG/actions/runs/41797778132), revision `9d84ba761015e4fe97e82eca84b3f41dc4d4f704`) and again inside the acceptance job at 09:24 Europe/Paris.

| Component | Digest | Pods |
|---|---|---|
| API | `sha256:10db1217d63466acfc5ae5084b808917fbe2947ee8fbe4e6ab849806c9048fd6` | `api-65dd4b74f6-*`, 1/1 Running, 0 restarts |
| Worker | `sha256:2ce6ee382c411426ff8f018df508d2506fc5e8734100d5b9b6cf23ce3f114cc8` | `ingestion-worker-db5fbc498-cqk6n`, 1/1 Running |
| Web | `sha256:e77c6685d4e97c57afb1347a82ad6588ee4a3627751ecbd7d36645c9af56db4f` | `web-b784dd4dd-*`, 1/1 Running, 0 restarts |

The API digest is the stall-window fix `e53ef513ff14bc3cc1fab3b8f44de8971ff07651`, built and scanned in [41790578638](https://github.com/coumarane/GraphRAG/actions/runs/41790578638) and promoted in [41792413175](https://github.com/coumarane/GraphRAG/actions/runs/41792413175). The worker and web digests are the Feature 002 images built from merge `1b3ea047acb93cca1882c7f32288bb0ecd3c56ce`. The worker image built from the API-only fix was not promoted.

The database backup used before the web promotion is run [41786577717](https://github.com/coumarane/GraphRAG/actions/runs/41786577717). Dump verification and the disposable restore both passed. Alembic current was `0013_upload_sessions`.

## Acceptance run

Workflow `Accept Feature 002 DEV`, run [41799205702](https://github.com/coumarane/GraphRAG/actions/runs/41799205702), at 09:24 Europe/Paris. Both jobs succeeded.

The product check passed on the acceptance ref. The browser journey, `frontend/e2e/rag-citation.spec.ts` at `a1e1d46`, signed in on https://chatwithdocs.org, uploaded a four-page PDF generated with fpdf2, waited until the page showed the run complete, and opened the evidence card. Playwright reported `1 passed (1.6m)`.

The in-cluster check then read document `01a1a5aa-0d79-707e-8ffb-569d16b88609`:

| Check | Result |
|---|---|
| Document | `ready` |
| Run | `completed` at 09:27 Europe/Paris. Heartbeat `2026-11-04T08:27:03Z`. `latest_warning` empty |
| Required stages | `PARSE`, `CHUNK`, `EMBED`, `INDEX_VECTOR`, and `INDEX_GRAPH` completed. Optional enrich and community stages were `skipped` and were not stored as the run warning |
| Page-2 citation | One citation, document `01a1a5aa-0d79-707e-8ffb-569d16b88609`, pages 2–2. The browser showed that document's `p.2` badge and `Page 2` evidence card |
| Graph | `INDEX_GRAPH` completed. The answer included one graph path |
| Worker | Ready. Restart count stayed 1 through this journey. Redis was not required for the pass |

The script printed `dev_acceptance_checks_passed`.

## Limitations left as debt

These did not fail the acceptance checks. Feature 002 does not take them further.

- Lexical scores from `InMemoryLexicalSearchStore` are term-frequency scores, not 0–1 cosines. A hybrid passage can clear the 0.12 floor from the lexical score while the dense score is below it. The floor tests assign both scores. They do not measure a live lexical index.
- The automated SC-001 trial is one `time.sleep(6)` on the ingestion loop, not three CPU-heavy parser runs.
- The worker process exited once with code 1 at 09:14 Europe/Paris and Kubernetes started it again in the same second. The accepted upload ran after that, on the new process, and did not add another restart. The retained log tail is a later Azure SDK logging error (`AttributeError` inside structlog while reading `graph.json`, HTTP 206). It did not fail the run.
- The acceptance print looked up `path_kind` on the graph path. `GraphPath` has no such field, so the printed kind was empty. The path count was 1 and `INDEX_GRAPH` completed.

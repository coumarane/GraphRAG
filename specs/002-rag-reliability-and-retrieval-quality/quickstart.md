# Quickstart: RAG Reliability and Retrieval Quality

This checks the feature locally. It does not upload to DEV, build an image, or promote a digest.

## Worker liveness

From `backend/`:

```bash
uv run pytest tests/unit/test_worker_liveness.py -q
```

The test holds a processing tick and requests `/health/live`. The response arrives within 5 seconds. Readiness is unchanged.

## Page citations and no-evidence

```bash
uv run pytest tests/unit/test_citation_page_range.py tests/unit/test_retrieval_evidence_floor.py -q
```

The four-page fixture is generated in the test with fpdf2 or an equivalent standard writer. A hand-built PDF body is not the fixture. Pages 2, 3, and 4 each have a sentence that appears on that page only. The page-2 citation includes page 2. The same sentence limited to the other document returns no evidence and `selection_has_no_supporting_evidence`.

## Graph paths and warnings

```bash
uv run pytest tests/unit/test_structural_graph_paths.py tests/unit/test_ingestion_state_machine.py -q
```

A finished structural graph returns a structural path or `graph_no_structural_path`. A skip of community summarization leaves the run `completed` and `latest_warning` empty. A `semantic_graph_failed` warning leaves the run `completed_with_warnings`.

## Browser journey

Local default, no DEV credentials:

```bash
cd frontend
npx playwright test e2e/rag-citation.spec.ts
```

DEV, only after this feature is reviewed and the credentials are injected outside the repo:

```bash
cd frontend
E2E_TARGET=dev \
E2E_BASE_URL=https://chatwithdocs.org \
E2E_ADMIN_EMAIL \
E2E_ADMIN_PASSWORD \
E2E_TENANT_KEY \
npx playwright test e2e/rag-citation.spec.ts
```

If `E2E_TARGET=dev` and any of those values is missing, the process exits before login. It does not use `admin@example.com` or `change-me-now-12`. The output does not print the password or a presigned URL.

## Release identity and workflow shape

From `backend/`:

```bash
uv run pytest tests/unit/test_dev_cors_policy.py tests/unit/test_release_identity.py tests/unit/test_workflow_heredoc.py -q
```

Promotion switches stay false. Serving digests and rollback digests both exist. They differ while `rollback_in_effect` is false.

## What this quickstart does not do

- It does not dispatch `promote-dev-image`.
- It does not change `infra/k8s/*/kustomization.yaml`.
- It does not run Alembic.
- It does not call the public API from a runner that receives Cloudflare error 1010 and then report that call as a browser success.

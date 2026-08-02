# Troubleshooting

## Local CLI uses in-memory stores

`enterprise-rag` defaults to `build_local_container()`. Data does not persist across processes unless you wire Postgres/MinIO/Qdrant/Neo4j adapters.

## `docker compose up` health failures

1. Confirm Docker has enough memory for Neo4j (≥1 GiB free).
2. Check `docker compose ps` and service logs (`docker compose logs neo4j`).
3. Neo4j password must satisfy complexity (`change-me-change-me` in compose).
4. Re-run migrations: `docker compose run --rm migrate`.

## Upload rejected

- MIME must be in the allowlist (`SecuritySettings.allowed_mime_types`).
- Size must be ≤ `MAX_UPLOAD_BYTES`.
- Page count must be ≤ `MAX_PAGES` after inspection.
- OOXML packages are scanned for zip-bomb / path-traversal members.

## SSRF on URL ingest

Only HTTPS is allowed by default. Localhost, private, link-local and cloud metadata addresses are blocked.

## Empty grounded answers

Retrieval may return no evidence in the local empty indexes. Ingest a document first, or inspect `/api/v1/metrics` and logs for retrieval warnings.

## Optional extras

Install parser/LLM extras when needed:

```bash
uv sync --extra parsers --extra llm --extra all
```

# MCP Server

Exposes ingest/query/retrieval as [Model Context Protocol](https://modelcontextprotocol.io)
tools, so external MCP clients (Claude Desktop, Cursor, or any MCP-compatible agent) can
call this platform directly instead of going through the REST API or CLI.

Implementation: `backend/src/graph_rag/mcp/`. Design rationale and constraints are recorded
in the MCP section of the plugin/pipeline-builder implementation plan referenced from
`docs/plugin-architecture-plan.md`.

## Enabling it

Gated behind `MCP_ENABLED` (default `false` — off unless explicitly turned on). When enabled,
the server mounts at:

```
{API_BASE_URL}/api/v1/mcp/
```

**Note the trailing slash** — `/api/v1/mcp` (no slash) 307-redirects to it; most MCP clients
don't follow redirects on the initial handshake, so configure clients with the slash included.

Requires the `mcp` extra to be installed (`uv sync --extra mcp`, or `pip install
'graph-rag[mcp]'`) — the Docker image installs it unconditionally so this is only a concern
for bare `uv`/`pip` installs.

## Auth model

MCP tool-call arguments are model-generated and must never be trusted as a source of tenant
identity — no tool takes a `tenant_id`/`tenant_key` parameter, and none ever will. Instead,
**one MCP connection resolves to one fixed tenant**, from the same headers the REST API's
service-key auth path already uses:

| Header | Purpose |
|---|---|
| `X-Api-Service-Key` | Must match `security.api_service_key` (`API_SERVICE_KEY` env var / secret). Required. |
| `X-Tenant-Key` | Resolve by tenant slug (e.g. `demo`, `chatwithdocs`). |
| `X-Tenant-ID` | Resolve by tenant UUID. Use instead of `X-Tenant-Key` if you have it. |
| `X-Principal` | Optional free-text identity label for audit/logging. |

Set these as static headers in your MCP client's server config — not per tool call. JWT/cookie
auth (the browser login flow) doesn't apply here; MCP access is service-key only.

## Tools

| Tool | Mirrors | Notes |
|---|---|---|
| `graphrag_ingest` | `POST /documents/ingest` | **URL-only** (`source_url`) — no `local_path`, to avoid handing an external client a path-traversal-shaped capability. Local-path ingest stays CLI-only. |
| `graphrag_query` | `POST /query` | Grounded answer with citations. Omits `answer_model_override` and raw `conversation_history` from the schema; doesn't persist a chat thread — one-shot per call. |
| `graphrag_retrieve` | `POST /retrieval/search` | Evidence search without answer generation. |
| `graphrag_inspect_document` | `GET /documents/{id}` | Metadata, optional chunk preview (`show_chunks`). |
| `graphrag_delete_document` | `DELETE /documents/{id}` | |
| `graphrag_reindex_document` | `POST /documents/{id}/reprocess` | `scope`: `full` \| `vectors` \| `graph`. |
| `graphrag_show_run` | `GET /ingestion-runs/{id}` | Run status + per-stage progress. |
| `graphrag_resume_run` | `POST /ingestion-runs/{id}/resume` | |

`graphrag_query`/`graphrag_retrieve` draw from the same daily `QuotaMetric.QUERIES` budget as
the web UI — an MCP caller is a second door into that budget, not a separate allowance.

## Testing / verification

`backend/scripts/verify_mcp_server.py` is a real MCP client (the official `mcp` SDK's
streamable-HTTP transport) you run from a terminal — it proves the server actually answers
over the wire, not just that the Python handler functions work in isolation.

```bash
cd backend
export GRAPH_RAG_MCP_SERVICE_KEY="..."   # never as a CLI arg -- shows up in shell history/ps
uv run python scripts/verify_mcp_server.py --tenant-key demo                       # list tools only
uv run python scripts/verify_mcp_server.py --tenant-key demo --tool graphrag_query \
  --question "What documents are available?"
uv run python scripts/verify_mcp_server.py --tenant-key demo \
  --url http://localhost:8000/api/v1/mcp/    # point at a local dev server instead of production
```

For local dev: run the API with `MCP_ENABLED=true` and a set `API_SERVICE_KEY`
(`docker compose` / `uvicorn` — see the root README's quick-start), then point the script's
`--url` at `http://localhost:8000/api/v1/mcp/`.

Automated tests: `backend/tests/unit/test_mcp_auth.py` (the tenant-resolution security gate —
proves a crafted tool-call argument can never influence which tenant resolves),
`test_mcp_tools.py` (authz/quota ordering per tool), `test_mcp_integration.py` (a real MCP
client against an in-process ASGI transport, no network needed).

## Connecting a real MCP client

Claude Desktop / Cursor / other clients configure remote MCP servers by URL + static headers
in their own config file (`claude_desktop_config.json`, `.cursor/mcp.json`, etc.) — the exact
JSON shape varies by client and version, so check that client's current MCP docs. In general
you'll be providing: the URL (`.../api/v1/mcp/`, trailing slash) and the four headers from the
auth table above as static request headers for that server entry.

Admins can also open **Operations → Plugins** in the web UI: `GET /api/v1/ops/mcp` powers an
MCP card with the live tool list and one-click Cursor / Claude config snippets.

## Known limitations

- No per-call multi-tenancy — one client connection is scoped to one tenant for its lifetime.
- `graphrag_ingest` is URL-only; there's no MCP path to ingest a local file.
- Deleting/reindexing require the target document to already exist and belong to the
  connection's tenant (ordinary 404, not a special MCP error).
- No live streaming of ingestion progress over MCP yet — poll `graphrag_show_run`.

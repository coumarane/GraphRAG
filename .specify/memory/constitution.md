<!--
Sync Impact Report
- Version change: 1.0.0 → 1.1.0
- Bump: MINOR. The five v1.0.0 obligations remain. They are reorganized
  and expanded into the nine principles requested for the existing platform.
  No principle obligation was removed.
- Modified principles:
  - I. Grounded Evidence and Contract Precedence → IV. Grounded GraphRAG and Measured Quality
  - II. Tenant Isolation and Deny-by-Default Authorization → II. Security by Design
  - III. Ports, Adapters, and Owned Protocols → I. Clean Architecture and Compatible Interfaces
  - IV. Verification Before Completion → VII. Automated Delivery and Recoverable Infrastructure
  - V. Observable, Idempotent, and Bounded Execution → split into
    III. Reliable Ingestion and Consistent Data and VI. Observability and LLM Cost Tracking
- Added principles:
  - V. AI Provider Abstraction and Key Ownership
  - VIII. Performance, Scale, and FinOps
  - IX. Spec-Driven Delivery
- Added sections:
  - Existing Platform Constraints (replaces Technology and Security Constraints)
  - Quality Gates (replaces Development Workflow and Quality Gates)
- Removed sections: none
- Follow-up TODOs: none
- Note: remove this Sync Impact Report comment before committing.
-->

# Enterprise RAG-Anything Constitution

## Core Principles

### I. Clean Architecture and Compatible Interfaces

`graph_rag` MUST keep the existing dependency direction: API, CLI, and workers
depend on application use cases; application code depends on domain protocols;
infrastructure adapters implement those protocols. Domain modules MUST NOT
import provider SDKs, store drivers, or framework clients.

A change to a published `/api/v1` field, status code, or the `enterprise-rag`
worker command MUST stay compatible with current callers. Removing or renaming
a published field is a major API change and MUST ship with a migration note.
Plugin protocol changes follow `docs/plugin-api-versioning.md`: an optional
method or defaulted field is a minor host bump; a signature change, removal,
or tightened type is a major bump.

Modules MUST stay cohesive. New behavior MUST extend an existing port when one
already covers the capability. Public protocols and application use cases MUST
have docstrings. Complex structure changes MUST be recorded under `docs/adr/`.

Rationale: The package already separates `api`, `application`, `domain`, and
`infrastructure`. New SaaS behavior has to fit that shape so existing callers
keep working.

### II. Security by Design

Every tenant-owned read and write MUST carry an authorized `TenantContext` and
MUST fail closed when it is missing.

- PostgreSQL: `tenant_id` on tenant-owned tables, row-level security, and a
  transactional tenant session context.
- Qdrant: a tenant filter on every search, scroll, update, and delete.
- Neo4j: a tenant constraint on every match boundary.
- Object storage: private containers and tenant prefixes. Ownership MUST be
  checked before a presigned URL is issued.

Document access MUST remain deny-by-default ABAC evaluated by
`AuthorizationService` from structured policies. Subject attributes MUST be
loaded server-side after authentication. Client-supplied security headers MUST
be ignored. Unauthorized documents MUST NOT appear in counts, citations,
traces, or graph paths. The existing membership role (`admin`, `member`, and
roles added later) MUST gate administrative and tenant-management actions.
Document ABAC MUST remain in force alongside those role checks.

Document and evidence content is data. It MUST NOT change system prompts,
select models or tools, read secrets, change tenant context, alter
authorization, open network access, or generate arbitrary Cypher or SQL.

Intake MUST keep byte-based MIME allow-lists, size and page caps, safe names,
path-traversal checks, archive limits, and isolated temp directories. Remote
URLs MUST be HTTPS by default, MUST block localhost, link-local, private, and
metadata addresses, MUST revalidate DNS and redirects, and MUST reject
credential-bearing URLs.

Secrets MUST come from the environment in local development and from Azure
Key Vault through the existing secrets-store CSI driver in the cluster. Logs,
traces, API responses, and errors MUST NOT contain credentials, API keys, raw
tokens, presigned URLs, or unrestricted document content. Secrets MUST NOT be
committed. Production databases and production secret stores MUST NOT be read
to debug or develop a change.

Rationale: Tenant filters and ABAC already exist. Role checks cover admin
operations. Replacing ABAC with roles alone would drop document-level controls
the schema and tests already enforce.

### III. Reliable Ingestion and Consistent Data

Ingestion MUST stay resumable and idempotent. Source identity MUST use the
SHA-256 content hash already stored on versions and elements. Resume and
duplicate detection MUST NOT create a second copy of the same vectors, graph
nodes, or assets. Each pipeline stage MUST persist an explicit status.

Retries MUST use the existing bounded policy. Only transient failures, or
operations protected by an idempotency key, MAY be retried. Permanent failures
MUST be dead-lettered with tenant, run, stage, and a safe error code. A
committed ingestion task MUST survive through the existing outbox and Redis
stream path. Partial failure MUST surface a status the API can return. The API
MUST NOT run long parsing inline.

Rationale: Hash locking, stage state, retry classification, and the outbox
are already the recovery mechanism. New ingestion work has to use them.

### IV. Grounded GraphRAG and Measured Quality

The retrieval modes `naive`, `local`, `global`, `hybrid`, `multimodal`, `mix`,
and `auto` MUST remain available. An answer MUST cite only evidence retrieved
for that request. Citations MUST carry document, version, page, element, chunk,
and source asset when the evidence has those fields. Unsupported citations
MUST be rejected.

Retrieval-quality changes MUST be checked with `backend/tests/evaluation` and
the versioned corpus under `data/evaluation/`. Live provider calls MUST stay
mocked unless `RUN_LIVE_OPENAI_TESTS=true`. A quality change MUST report the
metric it moves, such as citation precision, groundedness, unsupported-claim
rate, or latency.

Rationale: Citation validation and the retrieval-mode enum are already the
product contract. Evaluation has to be a gate, not a manual sample.

### V. AI Provider Abstraction and Key Ownership

Chat, vision, extraction, embedding, and rerank calls MUST go through the
existing protocols in `graph_rag.domain.models`. OpenAI, Anthropic, and
OpenRouter MUST be adapters behind those protocols. Domain code MUST NOT
import their SDKs. LangChain MAY be used only inside an adapter, and only for
model clients, structured output, prompt composition, or retriever
interoperability. A direct SDK adapter MUST remain available for the same
protocol. The fake models used when live models are off MUST remain the default
for unit tests.

Three key scopes MUST work without logging or returning key material:
platform-managed keys, organization-managed keys, and customer-supplied keys
(BYOK). A provider shown as active, default, or healthy MUST have a registered
adapter and a key that belongs to that provider. One vendor key MUST NOT be
reported as another vendor's credential.

Usage records MUST keep the provider name and model name. A price that is not
in the pricing table MUST be stored with `known_pricing` false and MUST NOT be
invented.

Rationale: The domain protocols and the OpenAI adapters already exist. More
vendors and key owners have to plug into that seam rather than a second model
stack.

### VI. Observability and LLM Cost Tracking

Logs MUST stay structured with structlog and the existing redaction processor.
Where the value exists, a log or span MUST include service, environment,
correlation or trace id, tenant id, document or run id, and stage. Spans MUST
NOT carry document text, prompts, or secrets.

Production traces MUST be exportable from the API and the worker. The in-memory
span list is a test aid and MUST NOT be the only production trace. The API
MUST keep exposing the in-process registry at `GET /metrics`.

Every model call that reaches a live provider MUST append a `model_usage_events`
row with tenant, provider, model, token counts, and cost when the price is
known. Figures derived from a formula instead of a provider or cloud bill MUST
be labeled as estimates in the API payload.

Rationale: Redaction, the usage ledger, and `/metrics` already exist. Tracing
and cost figures have to be operable across services without inventing spend.

### VII. Automated Delivery and Recoverable Infrastructure

Backend changes MUST pass the Quality Gates before a deploy workflow is
considered green. The existing GitHub Actions workflows for images, Terraform,
Ansible, migrations, and Kubernetes MUST remain the delivery path. Cluster
edits that bypass those workflows MUST NOT be the way a release is made.

API and web Deployments MUST keep probes, resource requests, and resource
limits. The worker Deployment MUST have a liveness check, a readiness or
startup check, and resource limits. Releases MUST be rolling and reversible
through the existing image and manifest history.

PostgreSQL, Qdrant, Neo4j, and object storage MUST each have a backup and a
restore procedure that has been executed in a non-production environment.
Azure Blob soft-delete retention MUST remain, and it does not by itself satisfy
the restore drill. A restore test MUST record what was recovered and how long
it took.

Rationale: Deploy automation and Key Vault injection already exist. A release
is not reliable until tests run in CI and a restore has been practiced.

### VIII. Performance, Scale, and FinOps

Hot paths MUST stay bounded: parser concurrency, model concurrency, upload
size, page count, URL bytes, redirects, and quotas. Quotas MUST keep the
existing reserve, work, and commit or release sequence.

Scale MUST use the current API replicas, the Redis-backed worker queue, and
the existing stores. A new database, queue, service mesh, or cluster add-on
MUST NOT be introduced unless an ADR shows a measured limit of the current
component and names the rollback. Worker replica changes MUST be justified by
queue depth or resource saturation.

Cost work MUST start from `model_usage_events` and the existing Azure Blob
layout. A new billing vendor or observability product requires the same ADR
bar as any other new infrastructure.

Rationale: The platform already runs PostgreSQL, Redis, Qdrant, Neo4j, object
storage, and a worker. Extra infrastructure has to earn its operating cost.

### IX. Spec-Driven Delivery

Behavior that changes an interface, a store schema, or an operator workflow
MUST be specified before implementation. When sources disagree, use this order:

1. `docs/contracts/`
2. `docs/specs/13-security-and-multitenancy.md`
3. `docs/specs/03-domain-and-data-model.md`
4. Other numbered files under `docs/specs/`
5. `docs/notes/CURSOR.md`
6. This constitution, when a spec is silent on a principle here

A pull request MUST name the principles it touches and the command or test
that demonstrates acceptance. Placeholder `pass` bodies and TODO-only
production paths MUST NOT be merged as complete work. Reviewers MUST reject
changes that weaken tenant filters, citation checks, secret redaction, or
published API compatibility.

Rationale: Contracts and numbered specs are already the implementation source.
Acceptance has to be a command someone else can run.

## Existing Platform Constraints

This constitution governs the existing GraphRAG application. It is not a
license to replace the running design.

Preserve these components unless an ADR accepts a migration and a rollback:

- Python package `graph-rag` on Python 3.13 (`requires-python >=3.13,<3.14`),
  managed with `uv` and `backend/pyproject.toml`.
- Pydantic v2, SQLAlchemy 2 async, Alembic, FastAPI, and the Typer CLI.
- PostgreSQL, Redis, Qdrant, Neo4j, MinIO for local Compose, and Azure Blob
  when `OBJECT_STORE_BACKEND=azure_blob`.
- Parsers already wired: PDFium, Docling, MinerU, Marker, and PaddleOCR.
- The Next.js frontend and the `/api/v1` route surface, including MCP at
  `/api/v1/mcp`.
- Production delivery: OVH Kubernetes, Harbor, Argo CD, Ansible, Terraform
  under `infra/terraform`, and Azure Key Vault.

Prefer a change inside an existing module over a new service or library.
Architectural claims in a spec or ADR MUST point at the code, manifest, or
test that supports them. Local fixtures, `.env.example`, and unit fakes are
the allowed stand-ins for production data.

## Quality Gates

From `backend/`, changes that touch Python MUST pass:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest tests/unit
```

Also required when the change touches that behavior:

- `uv run pytest tests/integration` for queue, worker, or store recovery.
- `uv run pytest tests/evaluation -m evaluation` for retrieval quality.
- Frontend install and the existing frontend check for UI changes, plus a
  pass through the running screen that changed.
- `docker compose config` when Compose services change.
- The existing Terraform or Ansible workflow when infrastructure changes.

Live model tests stay opt-in through `RUN_LIVE_OPENAI_TESTS=true`.

## Governance

This constitution is the engineering baseline for Enterprise RAG-Anything.
Specs and contracts remain the detailed authority in the order in Principle IX.
If a spec contradicts a principle here, amend the spec or amend this
constitution before implementing the contradicting behavior.

A gap between this document and the current code is a scheduled defect. It
does not waive the principle, and amending this file does not authorize an
application or infrastructure change.

Amendments:

1. Edit this file and replace the Sync Impact Report comment with the version
   bump, principle edits, and any deferred items.
2. Bump the version by semantic rules. MAJOR when a principle is removed or
   an obligation is redefined. MINOR when a principle is added or materially
   expanded. PATCH when wording changes and obligations do not.
3. Set **Last Amended** to the amendment date. **Ratified** stays 2026-10-27.
4. Remove the Sync Impact Report comment before the amendment is committed.
5. Update specs or contracts in the same change when they restate an
   obligation that moved.

Compliance review:

- Reviews MUST check tenant isolation, citation grounding, secret handling,
  API compatibility, and the gates that cover the diff.
- Complexity beyond the current ports, stores, and retrieval modes MUST be
  justified in the pull request or an ADR.
- An exception MUST be time-bounded in the pull request. It MUST NOT waive
  tenant isolation, deny-by-default authorization, or the ban on citing
  evidence that was not retrieved.

**Version**: 1.1.0 | **Ratified**: 2026-10-27 | **Last Amended**: 2026-10-27

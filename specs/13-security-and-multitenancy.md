# 13 — Security and Multitenancy

## Tenant context

Resolve tenant context from authenticated identity for APIs. CLI tenant input is permitted only for trusted administrative execution.

Every tenant-owned protocol method must accept a typed `TenantContext` or derive it from an authorized request scope.

## PostgreSQL

- add `tenant_id` to every tenant-owned table;
- define row-level-security policies;
- set tenant session context transactionally;
- test reads and writes across tenants;
- use least-privilege application roles.

## Qdrant

Every search, scroll, update and delete operation requires a tenant filter. Repository methods must fail when tenant context is absent.

## Neo4j

Every node and relationship query is tenant-scoped. Apply tenant constraints at every match boundary, not only the final return.

## MinIO

- private buckets;
- tenant-based object prefixes;
- short-lived presigned URLs;
- validate ownership before URL generation;
- encrypt transport;
- rotate credentials.

## File security

- byte-based MIME detection;
- allowed-type list;
- maximum file and page size;
- safe filenames;
- path-traversal prevention;
- archive-bomb protection;
- temporary-directory isolation;
- optional malware scanning hook;
- parser subprocess limits.

## Remote URL ingestion

- allow HTTPS by default;
- block localhost, link-local, private and metadata-service addresses;
- resolve DNS safely and revalidate redirects;
- cap redirects and download bytes;
- enforce content-type and timeout;
- reject credential-bearing URLs.

## Prompt injection

Document content is data, not instructions. It may not:

- change system prompts;
- select models or tools;
- request secrets;
- change tenant context;
- alter authorization;
- trigger network access;
- generate arbitrary Cypher or SQL.

## Secrets and logging

Never log credentials, API keys, raw authorization tokens, presigned URLs or unrestricted document contents. Provide redaction filters.

## Attribute-based access control (ABAC)

Authorization is deny-by-default and evaluated by `AuthorizationService` from structured JSON policies (no executable user code).

Subject attributes are loaded server-side from the user and `tenant_memberships` tables after JWT authentication. Client-supplied security headers are ignored.

Document resources carry first-class security fields (`owner_user_id`, `department`, `country`, `business_unit`, `classification`, `required_clearance`, `allowed_groups`) in addition to `security_labels`.

Store-level enforcement:

- **PostgreSQL** — tenant RLS remains mandatory; document list/get is filtered by ABAC predicates.
- **Qdrant** — payload includes security attributes; search must include tenant filter and is scoped to authorized `document_ids` (fail closed when scope is empty).
- **Neo4j** — MATCH remains tenant-scoped; claim/graph lookups accept authorized `document_ids` constraints.
- **MinIO** — prefix isolation remains; `document.read` must be authorized before get/presign.

Unauthorized documents must not appear in counts, citations, traces, or graph paths.

## Quotas

Quotas are enforced server-side with atomic reserve → work → commit/release. Tenant assignments are a ceiling over user assignments.

Default metrics: documents, pages, storage bytes, queries (day/month), OCR pages, vision calls, LLM tokens, embedding tokens.

Exceeded quotas map to HTTP 429 (`quota_exceeded`) with `{quota,limit,used,remaining,reset_at}`. Authorization denials map to HTTP 403.


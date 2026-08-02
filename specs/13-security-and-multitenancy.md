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

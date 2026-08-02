# Multitenancy

Every tenant-owned record carries `tenant_id`. API resolves tenant from `X-Tenant-ID` or `X-Tenant-Key`. CLI `--tenant-id` is for trusted admin execution.

Stores:

- PostgreSQL: RLS helpers + tenant session GUC
- Qdrant: tenant filter required on search/delete
- Neo4j: tenant predicate on every match
- MinIO: `tenants/{tenant_id}/documents/...` prefixes

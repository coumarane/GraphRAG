
Add user management, authorization, and quota management to the existing `graphrag` solution.

## Objective

Implement:

* user management;
* organizations/tenants;
* attribute-based access control (ABAC), not classic RBAC;
* document-level access policies;
* query/retrieval authorization;
* usage tracking;
* quotas for document ingestion and querying;
* quota enforcement before expensive processing starts.

## 1. User management

Support:

* users;
* tenants/organizations;
* user membership in one or more tenants;
* user status: active, disabled, suspended;
* user attributes;
* tenant attributes;
* document/resource attributes.

Example user attributes:

```text
department
country
business_unit
job_level
clearance_level
groups
cost_center
employment_type
```

Do not base authorization only on fixed roles such as `admin`, `reader`, or `editor`.

Roles may exist as optional attributes, but authorization must be evaluated through ABAC policies.

## 2. ABAC authorization

Implement an application-owned authorization engine.

Authorization decisions must evaluate:

```text
subject attributes
resource attributes
action
tenant
environment/context
```

Conceptually:

```text
allow(subject, action, resource, context)
```

Example policy:

```text
Allow document.read when:
subject.tenant_id == resource.tenant_id
AND
subject.country == resource.country
AND
subject.clearance_level >= resource.required_clearance
```

Another example:

```text
Allow document.ingest when:
subject.tenant_id == resource.tenant_id
AND
subject.attributes["can_ingest"] == true
```

Supported actions should include at least:

```text
document.upload
document.read
document.delete
document.reindex
document.manage
query.execute
query.cross_document
graph.query
admin.users.manage
admin.policies.manage
admin.quotas.manage
```

Centralize authorization.

Do not scatter authorization conditions directly across API routes.

Create something like:

```python
class AuthorizationService(Protocol):
    async def authorize(
        self,
        subject: SubjectContext,
        action: Action,
        resource: ResourceContext,
        environment: EnvironmentContext,
    ) -> AuthorizationDecision:
        ...
```

Default behavior must be:

```text
DENY
```

unless an explicit policy allows the operation.

## 3. Document access control

Every document must support security attributes such as:

```text
tenant_id
owner_user_id
department
country
business_unit
classification
required_clearance
allowed_groups
custom_security_attributes
```

Authorization must apply during both storage access and retrieval.

This is critical:

Do not retrieve unauthorized chunks and then remove them after retrieval.

Apply authorization filters before or during:

* PostgreSQL queries;
* Qdrant vector search;
* Neo4j graph traversal;
* MinIO asset access;
* cross-document retrieval.

A user must never be able to infer the existence of unauthorized documents through:

* search results;
* embeddings;
* graph relationships;
* citations;
* document counts;
* error messages.

## 4. Qdrant ABAC filtering

Store required authorization attributes in the Qdrant payload.

Example:

```json
{
  "tenant_id": "tenant-1",
  "document_id": "doc-123",
  "country": "FR",
  "department": "R&D",
  "classification": "INTERNAL",
  "required_clearance": 2,
  "allowed_groups": ["research"]
}
```

Build authorization-aware Qdrant filters before executing vector searches.

Tenant filtering is mandatory.

## 5. Neo4j ABAC filtering

Every tenant-owned graph node must contain:

```text
tenant_id
```

Add resource/security attributes where necessary.

All graph retrieval must enforce ABAC constraints before returning nodes, relationships, claims, chunks, or evidence.

Do not first traverse everything and filter afterwards.

## 6. User and policy persistence

Create PostgreSQL entities for at least:

```text
users
tenants
tenant_memberships
user_attributes
authorization_policies
policy_versions
quota_plans
quota_assignments
usage_events
usage_counters
```

Policies should be data-driven and versioned.

Store policy conditions in a controlled structured format.

Do not execute arbitrary Python or user-supplied code as policy logic.

## 7. Quota system

Implement configurable quotas per:

```text
tenant
user
```

Tenant quota must act as the upper boundary.

User quota must not bypass tenant quota.

Support limits for:

```text
documents uploaded
documents processed
pages processed
storage bytes
OCR pages
vision-model calls
LLM input tokens
LLM output tokens
embedding tokens
queries
cross-document queries
graph queries
```

Support quota periods such as:

```text
daily
monthly
total
```

Example quota plan:

```yaml
quotas:
  documents_per_month: 100
  pages_per_month: 10000
  storage_bytes: 10737418240

  queries_per_day: 500
  queries_per_month: 10000

  llm_tokens_per_month: 5000000
  embedding_tokens_per_month: 10000000

  vision_calls_per_month: 2000
  ocr_pages_per_month: 5000
```

## 8. Quota enforcement

Check quota before starting expensive operations.

Example ingestion flow:

```text
request
→ authenticate
→ authorize document.upload
→ inspect file
→ estimate required quota
→ reserve quota
→ process document
→ record actual usage
→ release unused reservation
```

Example query flow:

```text
query
→ authenticate
→ authorize query.execute
→ check query quota
→ reserve usage
→ retrieve authorized evidence
→ call LLM
→ record actual tokens
```

Prevent race conditions.

Two concurrent requests must not both consume the same remaining quota.

Use transactional quota reservation or an equivalent atomic mechanism.

## 9. Usage accounting

Create immutable usage events.

Example:

```text
user_id
tenant_id
operation
resource_id
usage_type
quantity
model
timestamp
correlation_id
```

Usage types:

```text
DOCUMENT
PAGE
STORAGE_BYTES
QUERY
CROSS_DOCUMENT_QUERY
OCR_PAGE
VISION_CALL
LLM_INPUT_TOKEN
LLM_OUTPUT_TOKEN
EMBEDDING_TOKEN
```

Maintain aggregated counters for efficient quota checks.

Do not rely only on aggregated counters as the audit source.

The immutable usage event log must remain the source of truth.

## 10. Quota exceeded behavior

Return explicit application errors.

Example HTTP response:

```json
{
  "error": "quota_exceeded",
  "quota": "queries_per_month",
  "limit": 10000,
  "used": 10000,
  "remaining": 0,
  "reset_at": "..."
}
```

Use HTTP `429` for exhausted usage quotas where appropriate.

Do not start an OpenAI, OCR, embedding, or parser operation after the relevant quota has already been exceeded.

## 11. API endpoints

Add APIs such as:

```text
GET    /api/v1/users/me
GET    /api/v1/users/me/usage
GET    /api/v1/users/me/quotas

GET    /api/v1/admin/users
POST   /api/v1/admin/users
PATCH  /api/v1/admin/users/{user_id}

GET    /api/v1/admin/policies
POST   /api/v1/admin/policies
PATCH  /api/v1/admin/policies/{policy_id}

GET    /api/v1/admin/quotas
POST   /api/v1/admin/quotas
PATCH  /api/v1/admin/quotas/{quota_id}
```

All admin endpoints must themselves use ABAC authorization.

## 12. Required tests

Add tests for:

```text
same tenant + allowed attributes → allowed
same tenant + insufficient clearance → denied
different tenant → denied
allowed department → allowed
wrong department → denied
allowed group → allowed
unauthorized document excluded from Qdrant results
unauthorized graph nodes excluded
unauthorized MinIO asset denied
quota available → operation succeeds
quota exhausted → operation rejected
concurrent requests cannot exceed quota
tenant quota overrides user allowance
monthly quota reset works
usage event recorded correctly
failed processing releases reserved quota correctly
```

Also test that unauthorized data never appears in:

```text
retrieval traces
citations
graph paths
cross-document answers
document counts
```

## 13. Implementation requirement

Before coding:

1. inspect the existing authentication and multitenancy implementation;
2. inspect `specs/13-security-and-multitenancy.md`;
3. propose the ABAC domain model;
4. propose the policy format;
5. propose the quota data model;
6. identify where authorization filters must be injected into PostgreSQL, Qdrant, Neo4j and MinIO;
7. identify all expensive operations requiring quota reservation.

Then implement the solution.

Do not replace ABAC with RBAC.

Do not hard-code authorization decisions in controllers.

Do not trust client-supplied tenant IDs or security attributes.

Do not allow quota checks only at UI level.

Authorization and quota enforcement must happen server-side.

Add migrations, APIs, application services, tests, documentation, and update the existing specifications where required.

Run:

```bash
uv run ruff check .
uv run mypy src
uv run pytest
```

Fix all failures before completion.

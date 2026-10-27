# Data Model: Reliable Document Upload and Ingestion

Existing documents, versions, runs, stages, outbox rows, and dead letters stay. This feature adds one table and one derived view of run progress. Status columns are already strings, so no Postgres enum change is required.

## Upload session

A short-lived intake record. It is not an ingestion stage.

| Field | Rules |
| --- | --- |
| `upload_id` | Primary key. Opaque id returned to the member. |
| `tenant_id` | Required. All reads and writes include the authorized tenant. |
| `user_id` | Member who started the session. Null only for a trusted administrative client. Recorded with `created_at` as who submitted and when (FR-019). |
| `document_id` | Null until acceptance. Set in the completion transaction. |
| `version_id` | Null until acceptance. |
| `staging_object_key` | Tenant-prefixed staging key. This is the only key the write URL may name. |
| `final_object_key` | Null until acceptance. Then the existing `original_object_key`. The write URL MUST NOT name it. |
| `source_filename` | Sanitized original name. |
| `title` | Member title. Empty means "derive from the file name at completion". |
| `declared_byte_size` | 1 through 104857600. A larger declaration is rejected with no session row. |
| `actual_byte_size` | Null until completion. Must be 1 through `declared_byte_size`. |
| `content_hash` | Null until completion streams the staging object. Then 64-char SHA-256. |
| `etag` | Null until the final object is written. Required on `completed`. |
| `object_version_id` | Null unless the backend returns a version id (Azure Blob versioning). Stored when present. |
| `mime_type` | Null until completion. Then an allow-listed type detected from bytes. |
| `status` | `pending`, `completed`, `expired`, `rejected`. |
| `expires_at` | Create time plus 15 minutes. |
| `ingestion_run_id` | Null until completion commits a run. |
| `source_url` | Null for a file upload. For remote intake, the HTTPS URL that was fetched. |
| `document_reservation_id` | Quota reservation for one document. |
| `storage_reservation_id` | Quota reservation for `declared_byte_size`. |
| `error_code` | Safe code when status is `rejected` or `expired`. |
| `created_at`, `updated_at` | UTC. |

Relationships:

- One session belongs to one tenant and at most one ingestion run.
- A pending session has no document and no version.
- Quota reservation ids point at existing `quota_reservations` rows. They reserve capacity before the document exists and release it if acceptance does not commit.

Validation:

- A second `complete` for a `completed` session returns the same document, version, and run. It does not insert a second outbox row or a second final object.
- Two concurrent completes take one row lock on the session. One commits. The other returns that same result.
- `complete` on `expired` or `rejected` fails and does not enqueue.
- A session whose `expires_at` has passed is swept to `expired` by every API replica. The sweep is idempotent: the staging object is deleted if present, both reservations are released, and no document row is created. Sweep runs inside the existing API publisher loop.
- Empty staging objects, objects larger than `declared_byte_size`, and disallowed types set the session to `rejected`, delete the staging object, release both reservations, and create no document.
- On success the API copies the staging object to `final_object_key`, stores `actual_byte_size` and `etag`, deletes the staging object, and only then inserts the document, version, run, stages, and outbox row in that same transaction. If the copy or the pin fails, the transaction rolls back and no document remains.
- Where the store supports it, the final object receives a retention or immutability policy. The write URL still cannot name that key when the policy is unavailable.
- A later PUT with the original write URL, or a size or etag mismatch on the final object, is a refusal. The worker does not parse a mismatched object.
- Remote intake leaves `staging_object_key` null. The API fetches the URL with the existing safe fetcher, applies the same size and type rules, writes the final object itself, and uses the same completion transaction. Private, local, and credentialed URLs are rejected with no document.

Uniqueness:

- Primary key `upload_id`.
- Unique (`tenant_id`, `staging_object_key`) where not null.
- Unique (`tenant_id`, `final_object_key`) where not null.
- Unique `ingestion_run_id` where not null.

## Document and version (existing, constrained)

Version rows gain nullable `etag` and `object_version_id` in revision `0013` only if those columns are absent. Existing version rows stay valid with nulls. Behavior:

- New uploads store the member title when it is non-empty.
- `content_hash`, `etag`, and byte size are written only in the acceptance transaction.
- Duplicate detection stays tenant-wide on `content_hash` for a non-deleted owner. It runs at completion, under the existing content-hash lock.
- A deleted owner's hash does not block a new upload. That rule already exists and stays.
- The worker reads `final_object_key` only when current size and etag match the version row.

State of the document:

```text
(no row while the session is pending, rejected, or expired)
accepted → ingesting → ready | partial | failed
                ↑          |
                └──────────┘  reprocess of the same final object
```

`registered`, `deleting`, and `deleted` stay as they are today. There is no `uploading` document status.

## Ingestion run and stage (existing)

Unchanged tables. Completion inserts one run and the existing ordered stage rows with the existing idempotency key inputs: tenant, version, stage, config fingerprint, content hash.

Derived progress, not stored:

| Condition | `progress_state` |
| --- | --- |
| Run status is `completed` or `completed_with_warnings` | `ready` |
| Run status is `partial` | `partial` |
| Run status is `failed` | `failed` |
| Run status is `cancelled` | `cancelled` |
| Run status is `pending` or `running`, and heartbeat is missing or older than 2 minutes | `stalled` |
| Otherwise | `running` |

`stalled` does not overwrite `ingestion_runs.status`. The response includes the last stage whose status is `completed` or `completed_with_warnings`. The heartbeat columns remain the source.

Retry bound stays the existing `RetryPolicy.max_attempts` of 3 (`should_retry` is true only while `attempt_count` is below 3). A stage already `completed` for the same tenant, version, config fingerprint, and content hash is not run again. The failure that makes `should_retry` false, and any permanent failure, writes one dead-letter row and then acks. There is no further attempt.

## Outbox and dead letter (existing)

Completion inserts one `ingest.queued` outbox row in the same transaction as the run. The publisher marks it published only after Redis accepts the message. Worker ack stays after a durable terminal success or a dead-letter write. No new columns.

## Quota counter (existing)

`usage_counters` unique key `(tenant_id, user_id, metric, period, period_key)` is the lock target.

Reserve, in one transaction:

1. Lock the counter row (`SELECT … FOR UPDATE`), inserting it if absent.
2. If `used + reserved + quantity` exceeds the tenant assignment, raise the existing quota error and store nothing.
3. Insert `quota_reservations` with status `reserved` and increment `reserved`.

Commit decrements `reserved`, increments `used` by the actual size, and marks the reservation `committed`. Release decrements `reserved` and marks it `released`. Actual size on completion must be less than or equal to the reserved size. A larger object is rejected and the reservation is released.

Organization scope uses `user_id` null on the tenant counter. A user assignment, when present, is an additional ceiling, matching the current quota model. Both locks are taken in a stable order (tenant row, then user row) so two API replicas cannot deadlock.

## Object

Staging bytes live under `staging_object_key`. Accepted bytes live under `final_object_key`. The database does not store the file. Completion streams the staging object, copies it to the final key, records size and etag, and deletes the staging key. On reject or expiry only the staging key is deleted. Tenant prefix checks stay on every presign, read, and delete. Containers stay private. MinIO CORS for local origins, and Azure Blob CORS for the web origin, allow the browser PUT and do not make the container public.

## What is not migrated

Existing documents, versions, runs, vectors, and graph rows are not rewritten. An in-flight multipart `POST /documents/ingest` keeps today's shape and does not require an upload session.

# Data Model: RAG Reliability and Retrieval Quality

No new table and no Alembic revision. The fields below already exist unless a response reason is marked additive.

## Passage

Stored chunk, parent or child.

| Field | Rule |
| --- | --- |
| `chunk_id` | Stable id already assigned by the chunker. |
| `parent_chunk_id` | Empty on a parent. Set on a child. |
| `document_id`, `version_id`, `tenant_id` | The owning document and organization. |
| `text` | The passage text that a citation may quote. |
| `page_start`, `page_end` | Pages of the elements in that passage. `page_end` is greater than or equal to `page_start`. A parent may span pages. A child uses its own elements. |

The citation page range is this range. It is not rewritten to a single first page.

## Evidence and citation

Returned by search and by the answer. Same passage, same range.

| Field | Rule |
| --- | --- |
| `document_id` | Inside the caller's organization and, when documents were selected, inside that selection. |
| `page_start`, `page_end` | The passage range. The quoted text occurs inside those pages. |
| `text` or `evidence` | The quoted passage, truncated only by the existing citation length. |
| `score` | Retrieval score used for the 0.12 floor. |
| `score_components.normalized` | Min-max view. Not the floor. |
| `score_components` source score | Present when fusion replaces `score` with a rank score, so the floor still sees the retrieval score. |

An empty evidence list is a successful no-evidence response when the warning says the selection did not support the question or the score was below the floor.

## Graph path

Existing `GraphPath` plus a reason when the list is empty and the caller asked for paths.

| Field | Rule |
| --- | --- |
| `nodes`, `relationships` | Belong to the caller's organization and the selected documents. |
| `metadata.path_kind` | `structural` or `entity`. |
| Response `warnings` | When `include_graph_paths` is true and `graph_paths` is empty: `graph_not_stored`, `graph_no_entity_match`, or `graph_no_structural_path`. |

Structural nodes are the document, version, and passages already written by `StructuralGraphBuilder`. Entity nodes remain the semantic graph.

## Run and step

Existing stage rows.

| Field | Rule |
| --- | --- |
| Stage `status` | `skipped` for an intentional optional idle step. `completed_with_warnings` for a genuine enrichment or parse failure. |
| Stage `warning` | Skip reason or genuine warning text. A skip reason does not change the run. |
| Run `status` | `completed` when no stage is `completed_with_warnings`. `completed_with_warnings` when one is. |
| `latest_warning` | The latest genuine warning. Empty when every warning belongs to a skipped stage. |
| Document `status` | `partial` remains needs review. It is not the status of a skipped optional step. |

Optional idle reasons that must not warn the run: `handled in parse/vision/chunk`, `document_intelligence not requested`, `document_intelligence disabled globally`, `document_intelligence disabled for this upload`, `document_intelligence provider/repository not configured`, `community summarization disabled`, `graph store disabled`.

Genuine warning prefixes: `semantic_graph_failed`, `vision_failed`, `needs_review`, `parser_fallback`, `parser_routing`.

## Release identity

File fields, not database columns.

| Field | Rule |
| --- | --- |
| Kustomize image digest | Serving identity for API, worker, and web. |
| `rollback_digests` | Previous serving identity for that part. |
| `promote.*` | Stay false until an explicit promotion of a reviewed image. |
| `rollback_in_effect` | Additive boolean. False unless an explicit rollback made serving equal the rollback identity. |

## Worker health

Not persisted.

| Field | Rule |
| --- | --- |
| Liveness | Answers within 5 seconds without the ingestion lock. |
| Readiness | Still fails when Postgres, Redis, or the object store is unavailable. |
| Restart count | Unchanged across parses that the worker finishes. |

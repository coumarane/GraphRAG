# 04 — Ingestion Pipeline

## State machine

Required stages:

1. `VALIDATE`
2. `HASH`
3. `REGISTER_DOCUMENT`
4. `STORE_ORIGINAL`
5. `INSPECT`
6. `SELECT_PARSER`
7. `PARSE`
8. `NORMALIZE`
9. `STORE_ELEMENTS`
10. `EXTRACT_ASSETS`
11. `ENRICH_IMAGES`
12. `ENRICH_TABLES`
13. `ENRICH_EQUATIONS`
14. `BUILD_CONTEXT`
15. `CHUNK`
16. `EMBED`
17. `INDEX_VECTOR`
18. `EXTRACT_GRAPH`
19. `RESOLVE_ENTITIES`
20. `INDEX_GRAPH`
21. `SUMMARIZE_COMMUNITIES`
22. `FINALIZE`

Each stage has status:

- pending;
- running;
- completed;
- completed_with_warnings;
- failed;
- skipped;
- cancelled.

## Idempotency

Every stage must define an idempotency key. Minimum key inputs:

- tenant;
- document version;
- stage name;
- parser/model/config fingerprint;
- source content hash.

On resume, skip completed stages only when the relevant configuration fingerprint has not changed.

## Parser fallback

Failure modes:

- `fail_fast`: terminate after selected parser fails;
- `fallback`: try configured alternatives;
- `best_effort`: preserve partial normalized output when it meets minimum quality.

Record every parser attempt, version, duration, warnings and failure category.

## Quality gates

Before normalization is accepted, validate:

- parsed page count is plausible;
- reading-order indices are unique per page;
- element pages are valid;
- extracted-text ratio meets profile threshold or OCR was attempted;
- required table/image assets exist;
- normalized IDs are stable and unique.

## Progress

Expose progress as:

- current stage;
- completed stages;
- pages processed;
- elements processed;
- estimated completion percentage based on weighted stages;
- latest warning;
- retry count.

Do not promise precise time remaining.

## Deletion

Deletion is a use case with its own staged transaction:

- mark document deleting;
- delete or tombstone Qdrant points;
- remove Neo4j provenance and orphan semantic nodes only;
- delete MinIO version assets;
- delete or archive PostgreSQL rows according to retention policy;
- invalidate Redis keys.

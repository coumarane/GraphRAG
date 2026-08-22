# Ingestion pipeline

Resumable stages are tracked in PostgreSQL. Workers dequeue tasks, execute stage handlers, persist progress and dead-letter exhausted failures.

Key stages: register → inspect → parse → enrich modalities → chunk → embed → index vectors → extract/project graph → finalize.

CLI: `graph-rag ingest SOURCE --tenant-id demo --wait`

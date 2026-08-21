# 16 — Deployment

## Local Docker Compose

Services:

- api;
- worker;
- PostgreSQL;
- Redis;
- MinIO;
- Qdrant;
- Neo4j.

Provide health checks and named volumes. Add CPU profile and optional GPU worker profile. The default setup must not require CUDA.

## Images

Create separate API and worker images from a shared base where practical. Use multi-stage builds, non-root users and pinned OS packages.

Parser-heavy dependencies may require a dedicated worker image. Keep the API image lightweight.

## Configuration

Provide:

- `.env.example`;
- `config/default.yaml`;
- `config/development.yaml`;
- `config/production.yaml`.

Precedence:

1. CLI arguments;
2. environment variables;
3. environment-specific YAML;
4. default YAML;
5. code defaults.

## Required environment categories

- application and logging;
- PostgreSQL;
- Redis;
- MinIO;
- Qdrant;
- Neo4j;
- OpenAI models and API key;
- parser paths and resource limits;
- concurrency and timeouts;
- security limits.

## Production concerns

- external secrets manager;
- managed TLS;
- private network access for stores;
- persistent backups;
- migration job;
- readiness that checks critical dependencies;
- rolling worker deployment with task leases;
- autoscaling based on queue depth and resource usage.

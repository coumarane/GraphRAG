# Deployment

Local stack is defined in `docker-compose.yml`.

## Services

| Service | Purpose |
|---|---|
| `postgres` | Document / run lifecycle |
| `redis` | Queue / cache |
| `minio` + `minio-init` | Object storage + bucket bootstrap |
| `qdrant` | Chunk vectors |
| `neo4j` | Knowledge graph |
| `migrate` | Alembic upgrade (one-shot) |
| `api` | FastAPI / Uvicorn |
| `worker` | Ingestion worker (CPU) |
| `worker-gpu` | Optional GPU profile |

## Images

- `Dockerfile` — multi-stage `api` / shared base (non-root user `app`)
- `backend/docker/Dockerfile.worker` — parser-capable worker image (still CPU-default; no CUDA required)

## Configuration precedence

1. CLI arguments  
2. Environment variables (nested `POSTGRES__HOST` or flat `POSTGRES_HOST`)  
3. `config/{environment}.yaml`  
4. `config/default.yaml`  
5. Code defaults  

## Production checklist

- External secrets manager for API keys and DB passwords
- Managed TLS termination
- Private network for data stores
- Persistent volume backups
- Readiness probes against critical dependencies
- Rolling worker deploys with task leases
- Autoscale workers from queue depth

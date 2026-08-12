# Enterprise RAG frontend

Next.js App Router UI for upload, grounded chat, and graph search. Browser traffic goes to
Next.js route handlers, which proxy to the FastAPI API (uploads land in MinIO when
`OBJECT_STORE_BACKEND=minio`).

Chat history is stored in the browser (`localStorage`) per tenant key.

## Local development

```bash
# terminal 1 — API (MinIO optional)
cd ..
docker compose up -d minio minio-init
export OBJECT_STORE_BACKEND=minio
uv run uvicorn enterprise_rag.api.app:get_app --factory --reload

# terminal 2 — UI
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Open http://localhost:3000

| Variable | Meaning |
|---|---|
| `RAG_API_URL` | Upstream FastAPI base URL (server-side) |
| `NEXT_PUBLIC_DEFAULT_TENANT_KEY` | Default tenant key in the UI |

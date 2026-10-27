# Staging environment

No staging namespace, hostname, or database is defined in this repository. The committed HTTPRoutes publish production only: `chatwithdocs.org` and `api.chatwithdocs.org`. `OBJECT_STORE_BACKEND` is the Key Vault secret `object-store-backend`. The same secret provider also mounts `MINIO_*` and `AZURE_BLOB_*`. This review did not read Key Vault, so the selected production backend is not recorded here. Compose and the local default are MinIO. The Azure README says an OVH deployment can switch to Azure Blob.

Do not apply the staging CORS file to the production storage account, and do not create these objects from a development session.

## Minimal staging on the existing OVH cluster

Use the current cluster and keep production workloads untouched.

1. Namespace `chatwithdocs-staging`.
2. HTTPRoutes for `staging.chatwithdocs.org` and `staging-api.chatwithdocs.org`. DNS and certificates stay separate from `chatwithdocs.org`.
3. Postgres database `enterprise_rag_staging` on the existing server. Run `alembic upgrade head` against that database only.
4. Redis logical database or key prefix that the production API and worker do not read.
5. MinIO bucket `enterprise-rag-staging`, private, with browser PUT allowed only from `https://staging.chatwithdocs.org`. Set `OBJECT_STORE_BACKEND=minio` for this namespace. Do not point staging at the production Azure account.
6. One API replica and one worker replica. The API init container already forces `INGEST_EXECUTION=worker` and `INGEST_QUEUE_BACKEND=redis`.
7. A staging Key Vault secret set. Do not reuse production database passwords or the production object-store credential.

## CORS

`infra/staging/azure-blob-cors.staging.json` is the rule for a future staging storage account. Its only origin is `https://staging.chatwithdocs.org`. It allows the headers a browser PUT needs, including `x-ms-blob-type`. It does not name `chatwithdocs.org`.

Local MinIO CORS is the Compose setting for `http://localhost:3000`, `http://127.0.0.1:3000`, `http://localhost:3010`, and `http://127.0.0.1:3010`. `infra/staging/validate_minio_cors.sh` checks a loopback MinIO and refuses any other endpoint. `mc anonymous get` in Compose reads the bucket policy; it does not grant public access. New buckets remain private.

If an operator later chooses Azure Blob for staging, apply the JSON to that staging account only, then repeat an OPTIONS preflight for `https://staging.chatwithdocs.org` before the web cutover.

# Feature 001 deployment to the existing DEV environment

There is no separate staging environment. Feature 001 deploys through the pipeline that already serves `https://chatwithdocs.org` and `https://api.chatwithdocs.org` on the OVH Kubernetes cluster:

GitHub Actions → Harbor (`harbor.safranys.com/chatwithdocs`) → a GitOps commit on `dev` → Argo CD.

Do not create a namespace, hostname, database, or bucket for staging. Do not dispatch an image build, a migration, or `Promote DEV image digest` from `feat/001-reliable-upload-ingestion`.

## What deploys

| Step | Trigger | Result |
|---|---|---|
| Feature checks | Push to `feat/001-reliable-upload-ingestion`, or a pull request. Workflow `Validate feature SHA`. | Backend unit tests, `tsc`, and Vitest. No image, no migration, no cluster change. |
| API image | Push to `dev` touching backend source, Alembic, lockfiles, `backend/docker/Dockerfile`, or the API workflow. Also `workflow_dispatch`. | Unit tests run first. Tag `api:<commit SHA>` only. Trivy then fails the job on a fixable CRITICAL or HIGH finding. |
| Worker image | Push to `dev` touching the same backend paths, the worker Dockerfiles, or the worker workflow. Also `workflow_dispatch`. | Same test and scan gate. Tag `worker:<commit SHA>` only. A base rebuild still moves the mutable tag `worker-base:dev`. |
| Web image | Push to `dev` touching `frontend/**` or the web workflow. Also `workflow_dispatch`. | Frontend `tsc` and Vitest run first. Tag `web:<commit SHA>` only, then the same Trivy gate. |
| GitOps | Tests and the image scan succeeded, `github.ref` is `refs/heads/dev`, and `infra/dev/release-gate.json` allows that component. | Would write the digest into `infra/k8s/{api,worker,web}/kustomization.yaml`. `promote.api`, `promote.worker`, and `promote.web` are false, so this step does not commit. |
| Controlled promotion | `workflow_dispatch` of `Promote DEV image digest`. GitHub environment `dev`. | Promotes one component after a successful `Backup DEV database` run, Alembic `0013_upload_sessions`, and a successful image workflow for that SHA. Web also requires `cors_ready` and matching API and worker digests. |
| Argo CD | Automated sync, prune, and self-heal. | `chatwithdocs-api` and `chatwithdocs-worker` track `dev` at `infra/k8s/api` and `infra/k8s/worker` in namespace `chatwithdocs-api`. `chatwithdocs-web` tracks `dev` at `infra/k8s/web` in namespace `chatwithdocs-web`. |
| Backup | `workflow_dispatch` of `Backup DEV database`. GitHub environment `dev`. | Dumps `database.safranys.com` as the `postgres` role, restores the archive into a disposable database, and stores the custom-format dump in the private `artifacts` container. |
| Migration | `workflow_dispatch` of `Run Database Migrations` only. | `backup_confirmed=true` is only an acknowledgement. The job also requires a successful `Backup DEV database` run from the last 24 hours whose blob checksum matches. A push of Alembic files does not migrate. |
| Emergency kubectl | `workflow_dispatch` with `acknowledge_argocd_bypass=true`. | Not the Feature 001 path. |

The feature branch cannot start a deployment. Its workflow is `Validate feature SHA`.

Argo CD follows the digest committed on `dev`. These digests are the rollback images, stored again in `infra/dev/release-gate.json`. The unit test checks that the kustomization files still carry them:

- API `sha256:b87a4646ea022aec2639e4f25e3969bd6c42e69735d96847d98e982383e44385`
- Worker `sha256:fdf5406658e3b12845efccb00a77a0ac41cbeab7572d7e54d7ad388702dcf5af`
- Web `sha256:690e22dff639dd779e8bca39bb3deb16d93a7d79036e4936170ec38a06746571`

## Gates

1. Backend unit tests finish before an API or worker image push. Frontend `tsc` and Vitest finish before a web image push.
2. The image tag is the validated commit SHA. A different dispatch tag fails the build. `api`, `worker`, and `web` are not tagged `:latest`.
3. Trivy uses `exit-code: 1` for fixable CRITICAL and HIGH findings. Unfixed findings stay ignored. A failed scan does not reach GitOps.
4. GitOps also requires the release gate. With the flags false, Harbor can hold the image and Argo CD stays on the digests above.
5. `Promote DEV image digest` is the only writer that should move a digest. It rejects a SHA whose matching image workflow did not succeed. For `web`, `infra/dev/assert-backend-promoted.sh` requires the API and worker digests already on `dev` to be `api:<SHA>` and `worker:<SHA>`.

## Object store and browser CORS

`OBJECT_STORE_BACKEND` is Key Vault secret `object-store-backend` on vault `graphrag-kv-api`. This session could not read it: the Azure CLI identity is in another tenant, and the kubeconfig for `193.70.35.121` is not authenticated. The Azure README still describes `azure_blob` as a later change away from MinIO, and the OVH node layout includes `/data/minio`. That is not the secret value.

Before web promotion, read the secret and apply one prepared file to the store it names. Both allow only `https://chatwithdocs.org`:

- `minio`: `infra/dev/minio-cors.dev.json` on the bucket named by `MINIO_BUCKET`
- `azure_blob`: `infra/dev/azure-blob-cors.dev.json` on the account named by `AZURE_BLOB_ACCOUNT_NAME`

The browser PUT sends `x-ms-blob-type: BlockBlob` only when the API process is using the Azure Blob adapter. A MinIO response carries an empty header map. Compose CORS does not include the DEV origin. `infra/staging/validate_minio_cors.sh` refuses every non-loopback endpoint. Terraform defines no blob `cors_rule`.

An OPTIONS preflight from `https://chatwithdocs.org` for `PUT` must succeed before `cors_ready` is set. The bucket or container stays private.

## Database backup and restore

`chatwithdocs_dev_user` is not a superuser and does not have `BYPASSRLS`. Sixteen public tables use `FORCE ROW LEVEL SECURITY`, so a dump as that role stops on `chat_conversations`. The administrative role is `postgres`. On the DEV server it has both `SUPERUSER` and `BYPASSRLS`, and it can log in. The backup workflow connects as `postgres` with `POSTGRES_ADMIN_PASSWORD` and stops unless the connected role still has one of those privileges. It refuses to connect as `chatwithdocs_dev_user`.

The workflow does not grant `BYPASSRLS`, disable row level security, or run `ALTER TABLE`. `pg_dump` uses `--format=custom --no-owner --no-acl` with `row_security=off`, and it does not pass `--enable-row-security`. That is the explicit bypass: only a superuser or `BYPASSRLS` role can keep `row_security` off, and the preflight check fails closed otherwise.

Dispatch `Backup DEV database` on `dev`, or send repository dispatch `backup-dev-database`. The job checks out `dev` either way. The job:

1. Reads the Alembic revision and PostgreSQL version.
2. Writes a custom-format dump.
3. Checks `pg_restore --list` for `documents` and `alembic_version`.
4. Restores the archive into a throwaway `postgres:18.6` database on the runner and compares public table counts with the source. That database is removed when the job ends. Nothing is created on `database.safranys.com`.
5. Uploads the dump to storage account `graphragdocsdevbmo9`, container `artifacts`, prefix `postgres-backups/dev/`. The container is private. The documents container is not used. GitHub keeps only `backup-metadata.json`, which has the checksum, revision, version, blob name, and verification result.
6. Deletes `postgres-backups/dev/` blobs older than 30 days. The storage lifecycle still moves `artifacts/` blobs to cool after 30 days and deletes them after 365 days. Blob soft delete keeps a deleted blob for 14 days.

The GitHub OIDC app `github-actions-graphrag-dev` has `Storage Blob Data Contributor` on the `artifacts` container only. Reapply that one assignment with:

```bash
python3 infra/github/oidc/assign_azure_roles.py \
  --client-id <azure-client-id> \
  --profile postgres-backup
```

Do not assign that role on the storage account. The account also contains the private `documents` container.

A successful run is fresh for 24 hours. `Run Database Migrations` and `Promote DEV image digest` both refuse to continue when that run is missing, older, for another database, or when the blob content MD5 differs. Setting `backup_confirmed=true` without the run does not pass.

To restore, download that blob with `az storage blob download --auth-mode login`, check the sha256 in the metadata, and run `pg_restore --no-owner --no-acl` into a new empty database. Restore over `chatwithdocs_db` only when revision `0013_upload_sessions` itself must be undone. Do not grant `BYPASSRLS` to the application role and do not disable row level security to read or restore the data.

## Migration and deploy order

Revision `0013_upload_sessions` revises `0012_document_search`. It adds nullable `etag` and `object_version_id` on `document_versions` and creates `upload_sessions`. Existing rows are not rewritten. Downgrade drops only that table and those two columns.

1. Merge the tested commit to `dev`. The image workflows may build and scan. They do not migrate, and the closed gate does not change the rollback digests.
2. Dispatch `Backup DEV database` on `dev`. Confirm the run succeeded, the log shows `admin_privilege=superuser` or `bypassrls`, and both `pg_restore_list` and `restore_database` passed. The metadata records the Alembic revision, PostgreSQL version, sha256, and blob name.
3. Dispatch `Run Database Migrations` with `backup_confirmed=true` and revision `0013_upload_sessions`. The workflow checks the backup run itself. Confirm `alembic current`.
4. Dispatch `Promote DEV image digest` for `api`, then `worker`, using the `dev` commit SHA whose image workflows succeeded. Wait until `chatwithdocs-api` and `chatwithdocs-worker` are Healthy and Synced. Startup pings Redis and refuses to serve when that ping fails. Later readiness checks Postgres.
5. Apply the CORS file for the secret's backend and pass the preflight.
6. Dispatch the web promotion for the same SHA with `cors_ready=true`. The workflow stops when the API or worker digest belongs to another commit.

Do not downgrade while an upload session exists or a new etag must be kept. A downgrade is a later dispatch with direction `downgrade` and revision `0012_document_search`, after the previous API and worker digests are serving and no upload is `pending`.

## Checks after Argo CD syncs

- API: `GET https://api.chatwithdocs.org/api/v1/health/ready` and `/api/v1/health/live`.
- Worker: pod Ready, probes `/health/live` and `/health/ready` on port 8081. A crash loop on startup means the Redis ping failed.
- Object store: the member PUT uses a key containing `/uploads/` and `/staging/`. Complete removes that key and leaves one private final object. A later PUT with the write URL does not change the final object.
- Tenant isolation: another tenant cannot complete the session. The bucket policy stays private.
- Progress: no document exists until complete. Progress then leaves `pending`, and the document list shows the document. With the worker stopped, progress becomes `stalled` and resumes when the worker is Ready.

## Rollback

Argo CD self-heals to the digests on `dev`. Do not use the emergency kubectl workflows.

1. Set the web digest back to `sha256:690e22dff639dd779e8bca39bb3deb16d93a7d79036e4936170ec38a06746571`. Wait until `chatwithdocs-web` is Healthy.
2. If the new API or worker cannot start, restore both in the same change: API `sha256:b87a4646ea022aec2639e4f25e3969bd6c42e69735d96847d98e982383e44385` and worker `sha256:fdf5406658e3b12845efccb00a77a0ac41cbeab7572d7e54d7ad388702dcf5af`. Wait until both applications are Healthy.
3. Leave revision `0013_upload_sessions` in place unless no upload session remains and the new etag values can be dropped. Restore the logical backup only when the migration itself must be undone.
4. Do not delete documents, runs, or objects as a rollback.

Trace export and restore drills are not implemented. The constitution records both as exceptions through 2027-01-31.

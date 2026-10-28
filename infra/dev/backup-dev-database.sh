#!/bin/bash
# Dump the DEV database as the administrative role, prove the archive restores,
# and store it in the private artifacts container. This script never changes
# roles, grants, or row level security on the source database.
set -euo pipefail

: "${PGPASSWORD:?POSTGRES_ADMIN_PASSWORD is required}"
: "${PGUSER:?}"
: "${PGHOST:?}"
: "${PGPORT:?}"
: "${PGDATABASE:?}"
: "${STORAGE_ACCOUNT:?}"
: "${CONTAINER:?}"

echo "::add-mask::${PGPASSWORD}"

PGSSLMODE="${PGSSLMODE:-prefer}"
BLOB_PREFIX="${BLOB_PREFIX:-postgres-backups/dev/}"
POSTGRES_IMAGE="${POSTGRES_IMAGE:-postgres:18.6}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
APP_ROLE="chatwithdocs_dev_user"
export PGSSLMODE PGPASSWORD PGUSER PGHOST PGPORT PGDATABASE

root=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
metadata_path="${GITHUB_WORKSPACE:-$(pwd)}/backup-metadata.json"
work=$(mktemp -d)
restore_container="dev-backup-restore-${GITHUB_RUN_ID:-$$}"

cleanup() {
  docker rm -f "$restore_container" >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

if [ "$PGUSER" = "$APP_ROLE" ]; then
  echo "Refusing to back up as the application role." >&2
  exit 1
fi

case "$BLOB_PREFIX" in
  postgres-backups/dev/) ;;
  *)
    echo "Refusing to store a database dump outside postgres-backups/dev/." >&2
    exit 1
    ;;
esac

access=$(az storage container show \
  --account-name "$STORAGE_ACCOUNT" \
  --name "$CONTAINER" \
  --auth-mode login \
  --query "properties.publicAccess" \
  --output tsv)
case "$access" in
  ""|None|null) ;;
  *)
    echo "Refusing to store a database dump in a public container." >&2
    exit 1
    ;;
esac

run_psql() {
  docker run --rm --network host \
    -e PGPASSWORD -e PGUSER -e PGHOST -e PGPORT -e PGDATABASE -e PGSSLMODE \
    -e PGOPTIONS="-c row_security=off" \
    "$POSTGRES_IMAGE" \
    psql -v ON_ERROR_STOP=1 "$@"
}

privilege=$(run_psql -At -F '|' -c "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user" | tr -d '\r' | tail -n 1)
admin_role=$(printf '%s' "${privilege%%|*}" | tr -d '[:space:]')
rest=${privilege#*|}
rolsuper=$(printf '%s' "${rest%%|*}" | tr -d '[:space:]')
rolbypass=$(printf '%s' "${rest#*|}" | tr -d '[:space:]')
echo "admin_role=${admin_role} rolsuper=${rolsuper} rolbypassrls=${rolbypass}"
if [ "$admin_role" = "$APP_ROLE" ]; then
  echo "Refusing to back up as the application role." >&2
  exit 1
fi
if [ "$rolsuper" = "t" ]; then
  admin_privilege="superuser"
elif [ "$rolbypass" = "t" ]; then
  admin_privilege="bypassrls"
else
  echo "Administrative role ${admin_role} cannot bypass row level security." >&2
  exit 1
fi

postgres_version=$(run_psql -At -c "SHOW server_version")
alembic_revision=$(run_psql -At -c "SELECT version_num FROM alembic_version")
revision_lines=$(printf '%s' "$alembic_revision" | awk 'NF { count += 1 } END { print count + 0 }')
if [ "$revision_lines" != "1" ]; then
  echo "Expected one Alembic revision on the source database." >&2
  exit 1
fi

count_sql="SELECT n.nspname || '.' || c.relname, (xpath('//row/count/text()', query_to_xml(format('SELECT count(*) FROM %I.%I', n.nspname, c.relname), true, true, '')))[1]::text FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY 1"

run_psql -At -F "$(printf '\t')" -c "$count_sql" > "$work/counts.before"

docker run --rm --network host --user root \
  -e PGPASSWORD -e PGUSER -e PGHOST -e PGPORT -e PGDATABASE -e PGSSLMODE \
  -e PGOPTIONS="-c row_security=off" \
  -v "$work:/backup" \
  "$POSTGRES_IMAGE" \
  pg_dump --format=custom --no-owner --no-acl --file=/backup/dev.dump

chmod 600 "$work/dev.dump"

docker run --rm --user root -v "$work:/backup" "$POSTGRES_IMAGE" \
  pg_restore --list /backup/dev.dump > "$work/restore.list"
if ! grep -q "TABLE DATA public documents" "$work/restore.list"; then
  echo "pg_restore --list did not find the documents table." >&2
  exit 1
fi
if ! grep -q "alembic_version" "$work/restore.list"; then
  echo "pg_restore --list did not find alembic_version." >&2
  exit 1
fi

docker run -d --name "$restore_container" \
  -e POSTGRES_PASSWORD=restore-check \
  -e POSTGRES_DB=restore_check \
  "$POSTGRES_IMAGE" >/dev/null

ready=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  if docker exec "$restore_container" pg_isready -U postgres -d restore_check >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
if [ "$ready" != "1" ]; then
  echo "The disposable restore database did not become ready." >&2
  exit 1
fi

docker cp "$work/dev.dump" "$restore_container:/tmp/dev.dump"
docker exec "$restore_container" \
  pg_restore --no-owner --no-acl --exit-on-error -U postgres -d restore_check /tmp/dev.dump
docker exec "$restore_container" \
  psql -v ON_ERROR_STOP=1 -U postgres -d restore_check -At -F "$(printf '\t')" -c "$count_sql" \
  > "$work/counts.after"
python3 "$root/backup_metadata.py" check-counts \
  --before "$work/counts.before" \
  --after "$work/counts.after"

checksums=$(python3 "$root/backup_metadata.py" checksum --file "$work/dev.dump")
sha256=$(printf '%s\n' "$checksums" | sed -n '1p')
content_md5=$(printf '%s\n' "$checksums" | sed -n '2p')
size_bytes=$(printf '%s\n' "$checksums" | sed -n '3p')

stamp=$(date -u +%Y%m%dT%H%M%SZ)
blob_name="${BLOB_PREFIX}${stamp}-${GITHUB_RUN_ID:-local}.dump"
az storage blob upload \
  --account-name "$STORAGE_ACCOUNT" \
  --container-name "$CONTAINER" \
  --name "$blob_name" \
  --file "$work/dev.dump" \
  --auth-mode login \
  --content-md5 "$content_md5" \
  --overwrite false \
  --only-show-errors

stored_md5=$(az storage blob show \
  --account-name "$STORAGE_ACCOUNT" \
  --container-name "$CONTAINER" \
  --name "$blob_name" \
  --auth-mode login \
  --query "properties.contentSettings.contentMd5" \
  --output tsv)
if [ "$stored_md5" != "$content_md5" ]; then
  echo "Uploaded blob checksum does not match the local archive." >&2
  exit 1
fi

az storage blob list \
  --account-name "$STORAGE_ACCOUNT" \
  --container-name "$CONTAINER" \
  --prefix "$BLOB_PREFIX" \
  --auth-mode login \
  --query "[].{name:name, modified:properties.lastModified}" \
  --output json > "$work/blobs.json"
python3 "$root/backup_metadata.py" expired-blobs \
  --blobs "$work/blobs.json" \
  --keep "$blob_name" \
  --retention-days "$RETENTION_DAYS" \
  > "$work/expired.txt"
while IFS= read -r old_blob; do
  [ -n "$old_blob" ] || continue
  az storage blob delete \
    --account-name "$STORAGE_ACCOUNT" \
    --container-name "$CONTAINER" \
    --name "$old_blob" \
    --auth-mode login \
    --only-show-errors
done < "$work/expired.txt"

python3 "$root/backup_metadata.py" write \
  --output "$metadata_path" \
  --host "$PGHOST" \
  --port "$PGPORT" \
  --database "$PGDATABASE" \
  --admin-role "$admin_role" \
  --admin-privilege "$admin_privilege" \
  --postgres-version "$postgres_version" \
  --alembic-revision "$alembic_revision" \
  --sha256 "$sha256" \
  --content-md5 "$content_md5" \
  --bytes "$size_bytes" \
  --account "$STORAGE_ACCOUNT" \
  --container "$CONTAINER" \
  --blob "$blob_name" \
  --retention-days "$RETENTION_DAYS"

echo "admin_role=${admin_role} admin_privilege=${admin_privilege}"
echo "postgres_version=${postgres_version}"
echo "alembic_revision=${alembic_revision}"
echo "sha256=${sha256}"
echo "bytes=${size_bytes}"
echo "blob=${STORAGE_ACCOUNT}/${CONTAINER}/${blob_name}"
echo "pg_restore_list=passed restore_database=passed row_counts_match=true"

#!/bin/sh
# Require a recent successful Backup DEV database run whose private blob
# still matches the recorded checksum. A backup_confirmed input is not enough.
set -eu

: "${GH_TOKEN:?}"
: "${EXPECTED_HOST:?}"
: "${EXPECTED_DATABASE:?}"
: "${STORAGE_ACCOUNT:?}"
: "${CONTAINER:?}"

MAX_AGE_HOURS="${MAX_AGE_HOURS:-24}"
root=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

runs=$(gh run list \
  --workflow backup-dev-database.yml \
  --status success \
  --limit 1 \
  --json databaseId,headBranch,conclusion,url)
run_id=$(printf '%s' "$runs" | python3 -c 'import json,sys; rows=json.load(sys.stdin); print(rows[0]["databaseId"] if rows else "")')
if [ -z "$run_id" ]; then
  echo "No successful Backup DEV database run. backup_confirmed does not replace that run." >&2
  exit 1
fi

gh run download "$run_id" --name dev-postgres-backup-metadata --dir "$work"
python3 "$root/backup_metadata.py" validate \
  --metadata "$work/backup-metadata.json" \
  --host "$EXPECTED_HOST" \
  --database "$EXPECTED_DATABASE" \
  --account "$STORAGE_ACCOUNT" \
  --container "$CONTAINER" \
  --max-age-hours "$MAX_AGE_HOURS"

blob_name=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["storage"]["blob"])' "$work/backup-metadata.json")
expected_md5=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["content_md5"])' "$work/backup-metadata.json")
stored_md5=$(az storage blob show \
  --account-name "$STORAGE_ACCOUNT" \
  --container-name "$CONTAINER" \
  --name "$blob_name" \
  --auth-mode login \
  --query "properties.contentSettings.contentMd5" \
  --output tsv)
if [ "$stored_md5" != "$expected_md5" ]; then
  echo "Stored backup checksum does not match backup run ${run_id}." >&2
  exit 1
fi

echo "Verified backup run ${run_id} for ${EXPECTED_HOST}/${EXPECTED_DATABASE}: ${blob_name}"

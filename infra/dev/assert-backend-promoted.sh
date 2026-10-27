#!/bin/sh
# Refuse a web promotion until the DEV kustomization digests match the
# API and worker images built from the same commit.
set -eu
sha="${1:?commit sha}"
registry="${REGISTRY_HOST:-harbor.safranys.com}"
project="${HARBOR_PROJECT:-chatwithdocs}"

digest_of() {
  docker buildx imagetools inspect "${registry}/${project}/$1:${sha}" \
    | awk '/^Digest:/ {print $2; exit}'
}

file_digest() {
  awk '/^[[:space:]]*digest:/ {print $2; exit}' "$1"
}

api_live="$(file_digest infra/k8s/api/kustomization.yaml)"
worker_live="$(file_digest infra/k8s/worker/kustomization.yaml)"
api_built="$(digest_of api)"
worker_built="$(digest_of worker)"

if [ -z "${api_built}" ] || [ "${api_live}" != "${api_built}" ]; then
  echo "API digest on dev (${api_live}) is not api:${sha} (${api_built})." >&2
  exit 1
fi
if [ -z "${worker_built}" ] || [ "${worker_live}" != "${worker_built}" ]; then
  echo "Worker digest on dev (${worker_live}) is not worker:${sha} (${worker_built})." >&2
  exit 1
fi
echo "API and worker digests on dev match ${sha}"

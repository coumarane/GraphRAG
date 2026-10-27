#!/bin/sh
# Check a local MinIO preflight. Refuses any host that is not loopback.
set -eu
origin="${1:-http://127.0.0.1:3010}"
endpoint="${MINIO_CORS_ENDPOINT:-http://127.0.0.1:9000/enterprise-rag/}"
case "$endpoint" in
  http://127.0.0.1:9000/*|http://localhost:9000/*) ;;
  *)
    echo "Refusing non-local MinIO endpoint: $endpoint" >&2
    exit 2
    ;;
esac
headers="$(curl -sS -D - -o /dev/null -X OPTIONS "$endpoint" \
  -H "Origin: $origin" \
  -H "Access-Control-Request-Method: PUT")"
printf '%s\n' "$headers" | grep -i "^access-control-allow-origin: $origin" >/dev/null
printf '%s\n' "$headers" | grep -i "^access-control-allow-methods: .*PUT" >/dev/null
echo "local MinIO allows PUT from $origin"

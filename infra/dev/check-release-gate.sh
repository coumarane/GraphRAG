#!/bin/sh
# Print promote=true or promote=false for one DEV component.
# A closed gate means the image may exist in Harbor and must not change Argo CD.
set -eu
component="${1:?component api, worker, or web}"
root=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
python3 - "$component" "$root/release-gate.json" <<'PY'
import json
import sys

component, path = sys.argv[1], sys.argv[2]
if component not in {"api", "worker", "web"}:
    raise SystemExit(f"unknown component {component}")
promote = json.loads(open(path, encoding="utf-8").read())["promote"][component]
if not isinstance(promote, bool):
    raise SystemExit(f"promote.{component} must be a boolean")
print(f"promote={'true' if promote else 'false'}")
PY

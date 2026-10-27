"""DEV object-store CORS names the live web origin and no second environment."""

from __future__ import annotations

import json
from pathlib import Path

_DEV = Path(__file__).resolve().parents[3] / "infra" / "dev"
_WEB_ORIGIN = "https://chatwithdocs.org"
_ABSENT = {
    "https://staging.chatwithdocs.org",
    "https://www.chatwithdocs.org",
    "https://api.chatwithdocs.org",
}


def test_dev_azure_cors_allows_the_web_route_only() -> None:
    policy = json.loads((_DEV / "azure-blob-cors.dev.json").read_text())
    origins = set(policy["allowed_origins"])
    assert origins == {_WEB_ORIGIN}
    assert origins.isdisjoint(_ABSENT)
    assert {"PUT", "OPTIONS"} <= set(policy["allowed_methods"])
    assert "x-ms-blob-type" in policy["allowed_headers"]
    assert policy["purpose"].startswith("Existing DEV storage account only")


def test_dev_minio_cors_allows_the_web_route_only() -> None:
    policy = json.loads((_DEV / "minio-cors.dev.json").read_text())
    rules = policy["CORSRules"]
    assert len(rules) == 1
    origins = set(rules[0]["AllowedOrigins"])
    assert origins == {_WEB_ORIGIN}
    assert origins.isdisjoint(_ABSENT)
    assert "PUT" in rules[0]["AllowedMethods"]
    assert "ETag" in rules[0]["ExposeHeaders"]
    assert "anonymous download" in policy["purpose"]


def test_release_gate_stays_closed_on_the_current_rollback_digests() -> None:
    gate = json.loads((_DEV / "release-gate.json").read_text())
    assert gate["promote"] == {"api": False, "worker": False, "web": False}
    kustomizations = {
        "api": _DEV.parents[0] / "k8s" / "api" / "kustomization.yaml",
        "worker": _DEV.parents[0] / "k8s" / "worker" / "kustomization.yaml",
        "web": _DEV.parents[0] / "k8s" / "web" / "kustomization.yaml",
    }
    for component, path in kustomizations.items():
        text = path.read_text()
        digest = gate["rollback_digests"][component]
        assert f"digest: {digest}" in text

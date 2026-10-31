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


def test_release_gate_stays_closed_and_records_rollback_digests() -> None:
    gate = json.loads((_DEV / "release-gate.json").read_text())
    assert gate["promote"] == {"api": False, "worker": False, "web": False}
    assert gate["rollback_digests"] == {
        "api": "sha256:b87a4646ea022aec2639e4f25e3969bd6c42e69735d96847d98e982383e44385",
        "worker": "sha256:fdf5406658e3b12845efccb00a77a0ac41cbeab7572d7e54d7ad388702dcf5af",
        "web": "sha256:690e22dff639dd779e8bca39bb3deb16d93a7d79036e4936170ec38a06746571",
    }

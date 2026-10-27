"""The staging CORS document must not name the production web origin."""

from __future__ import annotations

import json
from pathlib import Path

_POLICY = (
    Path(__file__).resolve().parents[3]
    / "infra"
    / "staging"
    / "azure-blob-cors.staging.json"
)
_PRODUCTION_ORIGINS = {
    "https://chatwithdocs.org",
    "https://www.chatwithdocs.org",
    "https://api.chatwithdocs.org",
}


def test_staging_cors_allows_the_proposed_web_origin_only() -> None:
    policy = json.loads(_POLICY.read_text())
    origins = set(policy["allowed_origins"])
    assert origins == {"https://staging.chatwithdocs.org"}
    assert origins.isdisjoint(_PRODUCTION_ORIGINS)
    assert {"PUT", "OPTIONS"} <= set(policy["allowed_methods"])
    assert "x-ms-blob-type" in policy["allowed_headers"]
    assert policy["purpose"].startswith("Staging storage account only")

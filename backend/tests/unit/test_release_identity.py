"""Serving digests and rollback digests are distinct while rollback is not in effect."""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PARTS = ("api", "worker", "web")


def _serving_digest(part: str) -> str:
    text = (_REPO / "infra" / "k8s" / part / "kustomization.yaml").read_text()
    match = re.search(r"(?m)^- digest:\s*(sha256:[0-9a-f]{64})\s*$", text)
    assert match, part
    return match.group(1)


def test_serving_digest_differs_from_rollback_while_rollback_is_not_in_effect() -> None:
    gate = json.loads((_REPO / "infra" / "dev" / "release-gate.json").read_text())
    assert gate["promote"] == {"api": False, "worker": False, "web": False}
    assert gate["rollback_in_effect"] is False
    for part in _PARTS:
        serving = _serving_digest(part)
        rollback = gate["rollback_digests"][part]
        assert _DIGEST.fullmatch(serving)
        assert _DIGEST.fullmatch(rollback)
        if gate["rollback_in_effect"] is False:
            assert serving != rollback

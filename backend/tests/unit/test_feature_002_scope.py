"""Feature 002 must leave the accepted upload path and parser child in place."""

from __future__ import annotations

import json
import os
import signal
from pathlib import Path

import pytest

from graph_rag.infrastructure.parsers.base import run_callable_isolated
from graph_rag.shared.exceptions import ParserError

_REPO = Path(__file__).resolve().parents[3]


def _sigill() -> None:
    os.kill(os.getpid(), signal.SIGILL)


def test_upload_session_commits_before_the_presigned_url_is_returned() -> None:
    source = (_REPO / "backend/src/graph_rag/api/routes/documents.py").read_text()
    function = source.split("async def create_upload_session", 1)[1].split("\nasync def ", 1)[0]
    commit_at = function.index("await container.commit_db()")
    return_at = function.index("return UploadCreateResponse")
    assert commit_at < return_at


@pytest.mark.asyncio
async def test_isolated_parser_still_maps_sigill_to_exit_132() -> None:
    parent = os.getpid()
    with pytest.raises(ParserError, match="Native parser process aborted") as caught:
        await run_callable_isolated(_sigill, timeout_seconds=30)
    assert os.getpid() == parent
    assert caught.value.details["exit_code"] == 132
    assert caught.value.details["signal"] == "SIGILL"


def test_release_gate_promotion_switches_stay_false() -> None:
    gate = json.loads((_REPO / "infra/dev/release-gate.json").read_text())
    assert gate["promote"] == {"api": False, "worker": False, "web": False}


def test_feature_002_adds_no_alembic_revision() -> None:
    versions = sorted((_REPO / "backend/alembic/versions").glob("*.py"))
    names = [path.name for path in versions]
    assert "0013_upload_sessions.py" in names
    assert all(not name.startswith("0014") for name in names)
    assert max(name.split("_", 1)[0] for name in names) == "0013"

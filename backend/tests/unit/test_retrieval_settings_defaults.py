"""RetrievalSettings must be a live knob, not dead config.

Config-composer Phase C0: prior to this, ``settings.retrieval`` was never
read anywhere -- ``RetrievalSearchRequest``/``QueryApiRequest`` hardcoded
``top_k=12, graph_depth=2, rerank=True`` as literal Pydantic field defaults.
These tests prove a configured override now actually reaches request
defaults, for both the HTTP API schemas and the MCP tool handlers that share
the same fallback.

Overrides go through YAML (``config/default.yaml`` already defines a
``retrieval:`` block), not env vars: once a field has a YAML-sourced value,
pydantic-settings treats it as an explicit constructor kwarg, which outranks
env vars in its precedence order -- matching how the config composer
(Phase C1/C2) is meant to change these values (a YAML diff into
``default.yaml``/``production.yaml``), not an env var.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from graph_rag.config.settings import clear_settings_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_settings_cache()
    yield
    clear_settings_cache()


def _use_config_dir_with_retrieval_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **overrides: object
) -> None:
    (tmp_path / "default.yaml").write_text(
        yaml.safe_dump({"retrieval": overrides}), encoding="utf-8"
    )
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    clear_settings_cache()


def test_retrieval_search_request_defaults_follow_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_config_dir_with_retrieval_overrides(
        monkeypatch, tmp_path, top_k=7, graph_depth=4, rerank=False, default_mode="hybrid"
    )

    from graph_rag.api.schemas import QueryApiRequest, RetrievalSearchRequest
    from graph_rag.domain.retrieval.enums import RetrievalMode

    request = RetrievalSearchRequest(question="anything")
    assert request.top_k == 7
    assert request.graph_depth == 4
    assert request.rerank is False
    assert request.mode == RetrievalMode.HYBRID

    query_request = QueryApiRequest(question="anything")
    assert query_request.top_k == 7
    assert query_request.graph_depth == 4
    assert query_request.rerank is False


def test_mcp_query_tool_falls_back_to_configured_retrieval_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_config_dir_with_retrieval_overrides(monkeypatch, tmp_path, top_k=9, rerank=False)

    from graph_rag.mcp.tools.retrieval import _common_request_kwargs

    kwargs = _common_request_kwargs({"question": "anything"})
    assert kwargs["top_k"] == 9
    assert kwargs["rerank"] is False

    # An explicit argument still wins over the configured default.
    kwargs = _common_request_kwargs({"question": "anything", "top_k": 3})
    assert kwargs["top_k"] == 3

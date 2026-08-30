"""Config composer: current-config read + validate-and-diff preview.

No live writes are exercised here because none exist -- the module never
touches disk or the running process's cached Settings; every test proves
the read/preview contract only.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from graph_rag.api.app import create_app
from graph_rag.api.dependencies import get_tenant_context
from graph_rag.application.config_composer import (
    ConfigPreviewRequest,
    build_current_config,
    preview_config_change,
)
from graph_rag.application.runtime.local import build_local_container
from graph_rag.config.settings import Settings, clear_settings_cache
from graph_rag.domain.authorization.models import Action
from graph_rag.domain.tenant import TenantContext


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_build_current_config_reflects_settings() -> None:
    settings = Settings()
    current = build_current_config(settings)
    assert current.chunking["parent_target_tokens"] == settings.chunking.parent_target_tokens
    assert current.retrieval["top_k"] == settings.retrieval.top_k
    assert current.parser_default_profile == settings.parsing.default_profile
    assert current.parser_profile_editable is False


def test_preview_valid_change_renders_focused_diff() -> None:
    settings = Settings()
    result = preview_config_change(
        settings, ConfigPreviewRequest(chunking={"parent_target_tokens": 3000})
    )
    assert result.valid is True
    assert not result.errors
    assert "-  parent_target_tokens: 2500" in result.diff
    assert "+  parent_target_tokens: 3000" in result.diff
    # Untouched section stays out of the diff entirely.
    assert "retrieval" not in result.diff


def test_preview_rejects_out_of_range_value() -> None:
    settings = Settings()
    result = preview_config_change(settings, ConfigPreviewRequest(retrieval={"top_k": -5}))
    assert result.valid is False
    assert any("top_k" in error for error in result.errors)
    assert result.diff == ""


def test_preview_with_no_changes_produces_empty_diff() -> None:
    settings = Settings()
    result = preview_config_change(settings, ConfigPreviewRequest())
    assert result.valid is True
    assert result.diff == ""


def _client(*, admin: bool) -> TestClient:
    container = build_local_container()
    app = create_app(container)
    tenant = TenantContext(
        tenant_id=uuid4(),
        tenant_key="demo",
        principal="ops@example.com",
        user_id=uuid4(),
        roles=("admin",) if admin else ("member",),
        attributes={"admin": True} if admin else {},
        user_status="active",
    )

    async def override_tenant() -> TenantContext:
        return tenant

    app.dependency_overrides[get_tenant_context] = override_tenant
    return TestClient(app)


def test_get_config_composer_requires_admin() -> None:
    member = _client(admin=False)
    denied = member.get("/api/v1/ops/config-composer")
    assert denied.status_code == 403, denied.text

    admin = _client(admin=True)
    allowed = admin.get("/api/v1/ops/config-composer")
    assert allowed.status_code == 200, allowed.text
    assert "parent_target_tokens" in allowed.json()["chunking"]


def test_preview_config_composer_requires_admin_and_validates() -> None:
    admin = _client(admin=True)
    ok = admin.post(
        "/api/v1/ops/config-composer/preview",
        json={"chunking": {"child_target_tokens": 500}},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["valid"] is True

    invalid = admin.post(
        "/api/v1/ops/config-composer/preview",
        json={"retrieval": {"top_k": 0}},
    )
    assert invalid.status_code == 200, invalid.text
    assert invalid.json()["valid"] is False

    member = _client(admin=False)
    denied = member.post("/api/v1/ops/config-composer/preview", json={})
    assert denied.status_code == 403, denied.text


def test_admin_settings_action_exists() -> None:
    assert Action.ADMIN_SETTINGS.value == "admin.settings"

"""Plugin catalog introspection tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from graph_rag.api.app import create_app
from graph_rag.api.dependencies import get_tenant_context
from graph_rag.application.plugins.catalog import build_plugin_catalog
from graph_rag.application.plugins.descriptors import PluginDescriptor
from graph_rag.application.plugins.registry import PluginRegistry
from graph_rag.application.runtime import build_local_container
from graph_rag.cli.main import app as cli_app
from graph_rag.config.settings import clear_settings_cache
from graph_rag.domain.authorization.models import Action
from graph_rag.domain.tenant import TenantContext


def _parser_factory(
    name: str,
    *,
    trust_tier: str = "core",
    extra: str | None = None,
) -> PluginDescriptor:
    return PluginDescriptor(
        plugin_name=name,
        capability="parser",
        trust_tier=trust_tier,  # type: ignore[arg-type]
        builder=lambda _settings: f"built-{name}",
        extra=extra,
        modules=("builtins",),
        structured=name != "pdfium",
    )


def test_catalog_includes_blocked_discovered_plugin() -> None:
    registry: PluginRegistry[Any] = PluginRegistry("parser", allowlist=[])
    registry.register_core(_parser_factory("pdfium", extra="parsers"))
    registry.register_discovered(_parser_factory("echo", trust_tier="community"))
    catalog = build_plugin_catalog(
        SimpleNamespace(
            plugins=SimpleNamespace(
                enabled=True,
                allow_core_override=False,
                allowlist=[],
                object_store=SimpleNamespace(backend="minio"),
                vector_store=SimpleNamespace(backend="qdrant"),
                graph_store=SimpleNamespace(backend="neo4j"),
                metadata_store=SimpleNamespace(backend="postgres"),
                ingest_queue=SimpleNamespace(backend="redis"),
                config={},
            ),
            parsing=SimpleNamespace(
                default_profile="balanced",
                profiles={"balanced": SimpleNamespace(primary="pdfium")},
            ),
        ),
        registries={"parser": registry},
    )
    by_name = {item.plugin_name: item for item in catalog.items}
    assert by_name["pdfium"].enabled is True
    assert by_name["pdfium"].origin == "core"
    assert by_name["pdfium"].selected is True
    assert by_name["echo"].enabled is False
    assert by_name["echo"].origin == "discovered"
    assert catalog.allowlist == []
    capabilities = {(row.capability, row.role, row.name) for row in catalog.selections}
    assert ("object_store", "backend", "minio") in capabilities
    assert ("parser", "inspector", "pdfium") in capabilities
    assert ("parser", "profile_primary", "pdfium") in capabilities


def test_cli_plugins_list_includes_core_parsers() -> None:
    runner = CliRunner()
    result = runner.invoke(cli_app, ["plugins", "list", "--output", "json"])
    assert result.exit_code == 0, result.output
    start = result.output.find("{")
    assert start >= 0, result.output
    payload = json.loads(result.output[start:])
    names = {item["plugin_name"] for item in payload["items"]}
    assert "pdfium" in names
    assert "text" in names
    assert "docling" in names


def _override_client(*, admin: bool) -> TestClient:
    container = build_local_container()
    app = create_app(container)
    tenant = TenantContext(
        tenant_id=uuid4(),
        tenant_key="demo",
        principal="ops@example.com",
        user_id=uuid4(),
        roles=("admin",) if admin else ("member",),
        attributes={"admin": True, "can_ingest": True} if admin else {"can_ingest": True},
        user_status="active",
    )

    async def override_tenant() -> TenantContext:
        return tenant

    app.dependency_overrides[get_tenant_context] = override_tenant
    return TestClient(app)


def test_ops_plugins_requires_admin() -> None:
    clear_settings_cache()
    try:
        member = _override_client(admin=False)
        denied = member.get("/api/v1/ops/plugins")
        assert denied.status_code == 403, denied.text

        admin = _override_client(admin=True)
        allowed = admin.get("/api/v1/ops/plugins")
        assert allowed.status_code == 200, allowed.text
        body = allowed.json()
        names = {item["plugin_name"] for item in body["items"]}
        assert "pdfium" in names
        assert body["enabled"] is True
    finally:
        clear_settings_cache()


def test_admin_plugins_action_exists() -> None:
    assert Action.ADMIN_PLUGINS.value == "admin.plugins"

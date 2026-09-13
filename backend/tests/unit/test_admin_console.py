"""Admin console (simple-rag parity) unit tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from graph_rag.api.app import create_app
from graph_rag.api.dependencies import get_tenant_context
from graph_rag.application.runtime import build_local_container
from graph_rag.domain.graph.models import GraphNode, GraphRelationship
from graph_rag.domain.graph.vocabulary import SemanticNodeLabel, SemanticRelationshipType
from graph_rag.domain.ids import deterministic_id, new_id
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.observability.log_buffer import (
    clear_log_events,
    record_log_event,
)
from graph_rag.shared.logging import configure_logging, get_logger, reset_logging_state


@pytest.fixture
def container(monkeypatch: pytest.MonkeyPatch):
    from graph_rag.config.settings import clear_settings_cache as clear

    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("APP_ENVIRONMENT", "development")
    clear()
    try:
        yield build_local_container()
    finally:
        clear()


@pytest.fixture
def client(container):
    return TestClient(create_app(container))


@pytest.fixture
def tenant_headers():
    return {
        "X-Tenant-Key": "demo",
        "X-Correlation-ID": str(new_id()),
    }


def _member_client(container) -> TestClient:
    app = create_app(container)
    tenant = TenantContext(
        tenant_id=uuid4(),
        tenant_key="demo",
        principal="member@example.com",
        user_id=uuid4(),
        roles=("member",),
        attributes={},
        user_status="active",
    )

    async def override_tenant() -> TenantContext:
        return tenant

    app.dependency_overrides[get_tenant_context] = override_tenant
    return TestClient(app)


def test_seeded_categories_and_chat_contexts(client, tenant_headers) -> None:
    categories = client.get("/api/v1/admin/console/categories", headers=tenant_headers)
    assert categories.status_code == 200, categories.text
    names = {item["name"] for item in categories.json()["items"]}
    assert "General" in names
    assert "Presentation" in names
    contexts = client.get("/api/v1/admin/console/chat-contexts", headers=tenant_headers)
    assert contexts.status_code == 200, contexts.text
    ctx_names = [item["name"] for item in contexts.json()["items"]]
    assert ctx_names[0] == "General Assistant"
    assert "Formulation Chemist" in ctx_names


def test_connector_crud_and_test(client, tenant_headers) -> None:
    created = client.post(
        "/api/v1/admin/console/connectors",
        headers=tenant_headers,
        json={
            "name": "Documents_ICE",
            "description": "Pdf parser",
            "site_url": "https://contoso.sharepoint.com",
        },
    )
    assert created.status_code == 201, created.text
    connector_id = created.json()["connector_id"]
    tested = client.post(
        f"/api/v1/admin/console/connectors/{connector_id}/test",
        headers=tenant_headers,
    )
    assert tested.status_code == 200, tested.text
    assert tested.json()["status"] == "active"
    missing = client.post(
        "/api/v1/admin/console/connectors",
        headers=tenant_headers,
        json={"name": "Broken"},
    )
    broken_id = missing.json()["connector_id"]
    failed = client.post(
        f"/api/v1/admin/console/connectors/{broken_id}/test",
        headers=tenant_headers,
    )
    assert failed.json()["status"] == "error"
    assert "401" in (failed.json()["last_error"] or "")
    disabled = client.post(
        f"/api/v1/admin/console/connectors/{connector_id}/disable",
        headers=tenant_headers,
    )
    assert disabled.json()["enabled"] is False
    deleted = client.delete(
        f"/api/v1/admin/console/connectors/{broken_id}",
        headers=tenant_headers,
    )
    assert deleted.status_code == 204


def test_category_and_chat_context_mutations(client, tenant_headers) -> None:
    created = client.post(
        "/api/v1/admin/console/categories",
        headers=tenant_headers,
        json={"name": "Safety", "parser": "docling", "description": "SDS packs"},
    )
    assert created.status_code == 201, created.text
    category_id = created.json()["category_id"]
    patched = client.patch(
        f"/api/v1/admin/console/categories/{category_id}",
        headers=tenant_headers,
        json={"parser": "mineru"},
    )
    assert patched.json()["parser"] == "mineru"
    listed = client.get("/api/v1/admin/console/categories", headers=tenant_headers)
    default_id = next(item["category_id"] for item in listed.json()["items"] if item["is_default"])
    denied = client.delete(
        f"/api/v1/admin/console/categories/{default_id}",
        headers=tenant_headers,
    )
    assert denied.status_code == 422
    ctx = client.post(
        "/api/v1/admin/console/chat-contexts",
        headers=tenant_headers,
        json={"name": "QA reviewer", "description": "Checks citations"},
    )
    assert ctx.status_code == 201, ctx.text
    context_id = ctx.json()["context_id"]
    toggled = client.patch(
        f"/api/v1/admin/console/chat-contexts/{context_id}",
        headers=tenant_headers,
        json={"visible": False},
    )
    assert toggled.json()["visible"] is False


def test_settings_and_insights_empty(client, tenant_headers) -> None:
    settings = client.get("/api/v1/admin/console/settings", headers=tenant_headers)
    assert settings.status_code == 200, settings.text
    assert settings.json()["parse_acceleration_mode"] == "cpu"
    assert settings.json()["danger_zone_enabled"] is True
    patched = client.patch(
        "/api/v1/admin/console/settings",
        headers=tenant_headers,
        json={"parse_acceleration_mode": "auto", "pipeline_audit_enabled": False},
    )
    assert patched.json()["parse_acceleration_mode"] == "auto"
    health = client.get("/api/v1/admin/console/document-health", headers=tenant_headers)
    assert health.status_code == 200
    assert health.json()["items"] == []
    processing = client.get("/api/v1/admin/console/processing", headers=tenant_headers)
    assert processing.json()["documents"] == 0
    billing = client.get("/api/v1/admin/console/billing", headers=tenant_headers)
    assert billing.status_code == 200
    costs = client.get("/api/v1/admin/console/cloud-costs", headers=tenant_headers)
    assert costs.status_code == 200
    providers = client.get("/api/v1/admin/console/providers", headers=tenant_headers)
    assert any(item["id"] == "openai" for item in providers.json()["items"])


def test_feedback_benchmarks_and_logs(client, tenant_headers) -> None:
    clear_log_events()
    record_log_event({"level": "ERROR", "event": "cpu_embedding_failed", "logger": "ingest"})
    record_log_event({"level": "INFO", "event": "batch_number", "logger": "worker"})
    logs = client.get(
        "/api/v1/admin/console/logs",
        headers=tenant_headers,
        params={"query": "cpu_embedding", "level": "ERROR"},
    )
    assert logs.status_code == 200, logs.text
    assert logs.json()["counts"]["ERROR"] >= 1
    assert logs.json()["items"]
    feedback = client.post(
        "/api/v1/admin/console/feedback",
        headers=tenant_headers,
        json={
            "question": "What is SY-KNP?",
            "rating": "negative",
            "citations_found": False,
            "answer_excerpt": "No sources found",
        },
    )
    assert feedback.status_code == 201, feedback.text
    summary = client.get("/api/v1/admin/console/feedback", headers=tenant_headers)
    assert summary.json()["knowledge_gaps"] == 1
    run = client.post(
        "/api/v1/admin/console/benchmarks/run",
        headers=tenant_headers,
        json={"config": "hybrid_rerank_k15"},
    )
    assert run.status_code == 200
    history = client.get("/api/v1/admin/console/benchmarks", headers=tenant_headers)
    assert history.json()["items"][0]["config"] == "hybrid_rerank_k15"


def test_graph_insights_and_consolidate(client, container, tenant_headers) -> None:
    tenant = TenantContext(
        tenant_id=deterministic_id("tenant", "demo"),
        tenant_key="demo",
    )
    store = container.graph_store
    doc_a = str(new_id())
    doc_b = str(new_id())
    keep = GraphNode(
        node_id=new_id(),
        label=SemanticNodeLabel.PRODUCT.value,
        tenant_id=tenant.tenant_id,
        properties={"name": "Calmaru", "document_id": doc_a},
    )
    drop = GraphNode(
        node_id=new_id(),
        label=SemanticNodeLabel.PRODUCT.value,
        tenant_id=tenant.tenant_id,
        properties={"name": "CALMARU", "document_id": doc_b},
    )
    rel = GraphRelationship(
        relationship_id=new_id(),
        relationship_type=SemanticRelationshipType.RELATES_TO.value,
        source_node_id=drop.node_id,
        target_node_id=keep.node_id,
        tenant_id=tenant.tenant_id,
        properties={},
    )
    store.nodes[keep.node_id] = keep
    store.nodes[drop.node_id] = drop
    store.relationships[rel.relationship_id] = rel
    insights = client.get("/api/v1/admin/console/graph", headers=tenant_headers)
    assert insights.status_code == 200, insights.text
    assert insights.json()["duplicate_groups"] >= 1
    merged = client.post("/api/v1/admin/console/graph/consolidate", headers=tenant_headers)
    assert merged.status_code == 200, merged.text
    assert merged.json()["merged_nodes"] >= 1
    after = client.get("/api/v1/admin/console/graph", headers=tenant_headers)
    assert after.json()["duplicate_groups"] == 0


def test_member_is_denied(container) -> None:
    member = _member_client(container)
    denied = member.get("/api/v1/admin/console/categories")
    assert denied.status_code == 403, denied.text


def test_structlog_buffer_captures_events() -> None:
    reset_logging_state()
    clear_log_events()
    configure_logging(level="INFO", json_logs=True, service_name="test-admin")
    logger = get_logger("admin.buffer")
    logger.error("pipeline_failed", document_id="doc-1")
    from graph_rag.infrastructure.observability.log_buffer import query_log_events

    items, counts = query_log_events(query="pipeline_failed")
    assert counts["ERROR"] >= 1
    assert items
    reset_logging_state()
    clear_log_events()


def test_danger_zone_clear_chat(client, tenant_headers) -> None:
    wiped = client.post("/api/v1/admin/console/danger/clear-chat", headers=tenant_headers)
    assert wiped.status_code == 200, wiped.text
    assert wiped.json()["deleted"] == 0

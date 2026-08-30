"""GET/POST /api/v1/document-intelligence/models route tests (Phase 2)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from graph_rag.api.app import create_app
from graph_rag.application.runtime import build_local_container
from graph_rag.domain.ids import new_id


@pytest.fixture
def container(monkeypatch: pytest.MonkeyPatch):
    from graph_rag.config.settings import clear_settings_cache

    monkeypatch.setenv("AUTH_ENABLED", "false")
    clear_settings_cache()
    try:
        yield build_local_container()
    finally:
        clear_settings_cache()


@pytest.fixture
def client(container):
    return TestClient(create_app(container))


@pytest.fixture
def tenant_headers():
    return {
        "X-Tenant-Key": "demo",
        "X-Correlation-ID": str(new_id()),
    }


def test_list_models_includes_builtins_with_no_custom_models(client, tenant_headers) -> None:
    response = client.get("/api/v1/document-intelligence/models", headers=tenant_headers)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    keys = {item["model_key"] for item in items}
    assert "sds" in keys
    assert "certificate_of_analysis" in keys
    sds = next(item for item in items if item["model_key"] == "sds")
    assert sds["is_builtin"] is True
    assert sds["model_id"] is None
    assert len(sds["fields"]) > 0


def test_create_custom_model_then_list_includes_it(client, tenant_headers) -> None:
    created = client.post(
        "/api/v1/document-intelligence/models",
        json={
            "model_key": "invoice",
            "name": "Invoice",
            "fields": [
                {"name": "invoice_number", "label": "Invoice number", "field_type": "string"},
                {
                    "name": "total_amount",
                    "label": "Total amount",
                    "field_type": "currency",
                    "default_selected": True,
                },
            ],
        },
        headers=tenant_headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["model_key"] == "invoice"
    assert body["model_type"] == "custom"
    assert body["is_builtin"] is False
    assert body["model_id"] is not None
    assert [f["name"] for f in body["fields"]] == ["invoice_number", "total_amount"]

    listed = client.get("/api/v1/document-intelligence/models", headers=tenant_headers)
    keys = {item["model_key"] for item in listed.json()["items"]}
    assert "invoice" in keys


def test_create_custom_model_forces_model_type_server_side(client, tenant_headers) -> None:
    """``model_type`` is not a client-settable field: request schema forbids it."""
    response = client.post(
        "/api/v1/document-intelligence/models",
        json={
            "model_key": "sneaky",
            "name": "Sneaky",
            "model_type": "prebuilt",
            "fields": [{"name": "x", "label": "X", "field_type": "string"}],
        },
        headers=tenant_headers,
    )
    assert response.status_code == 422, response.text


def test_create_custom_model_rejects_invalid_field_type(client, tenant_headers) -> None:
    response = client.post(
        "/api/v1/document-intelligence/models",
        json={
            "model_key": "bad",
            "name": "Bad",
            "fields": [{"name": "x", "label": "X", "field_type": "not-a-real-type"}],
        },
        headers=tenant_headers,
    )
    assert response.status_code == 422, response.text


def test_create_custom_model_rejects_unknown_entity_label(client, tenant_headers) -> None:
    response = client.post(
        "/api/v1/document-intelligence/models",
        json={
            "model_key": "invoice-bad-label",
            "name": "Invoice",
            "fields": [{"name": "vendor_name", "label": "Vendor", "field_type": "string"}],
            "field_entity_mappings": {"vendor_name": {"label": "NotARealLabel"}},
        },
        headers=tenant_headers,
    )
    assert response.status_code == 422, response.text


def test_create_custom_model_rejects_mapping_for_unknown_field(client, tenant_headers) -> None:
    response = client.post(
        "/api/v1/document-intelligence/models",
        json={
            "model_key": "invoice-dangling-mapping",
            "name": "Invoice",
            "fields": [{"name": "vendor_name", "label": "Vendor", "field_type": "string"}],
            "field_entity_mappings": {"not_a_field": {"label": "Organization"}},
        },
        headers=tenant_headers,
    )
    assert response.status_code == 422, response.text


def test_create_custom_model_round_trips_promote_flag_and_field_entity_mapping(
    client, tenant_headers
) -> None:
    created = client.post(
        "/api/v1/document-intelligence/models",
        json={
            "model_key": "invoice-mapped",
            "name": "Invoice",
            "fields": [
                {
                    "name": "vendor_name",
                    "label": "Vendor",
                    "field_type": "string",
                    "promote_to_document_metadata": True,
                },
            ],
            "field_entity_mappings": {
                "vendor_name": {"label": "Organization", "relationship_type": "MENTIONS"}
            },
        },
        headers=tenant_headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["fields"][0]["promote_to_document_metadata"] is True
    assert body["field_entity_mappings"] == {
        "vendor_name": {"label": "Organization", "relationship_type": "MENTIONS"}
    }

    listed = client.get("/api/v1/document-intelligence/models", headers=tenant_headers)
    item = next(i for i in listed.json()["items"] if i["model_key"] == "invoice-mapped")
    assert item["fields"][0]["promote_to_document_metadata"] is True
    assert item["field_entity_mappings"] == {
        "vendor_name": {"label": "Organization", "relationship_type": "MENTIONS"}
    }


def test_custom_models_are_tenant_scoped(client, tenant_headers) -> None:
    client.post(
        "/api/v1/document-intelligence/models",
        json={
            "model_key": "tenant-demo-only",
            "name": "Tenant demo only",
            "fields": [{"name": "x", "label": "X", "field_type": "string"}],
        },
        headers=tenant_headers,
    )
    other_tenant_headers = {"X-Tenant-Key": "other", "X-Correlation-ID": str(new_id())}
    listed = client.get("/api/v1/document-intelligence/models", headers=other_tenant_headers)
    assert listed.status_code == 200, listed.text
    keys = {item["model_key"] for item in listed.json()["items"]}
    assert "tenant-demo-only" not in keys
    # Built-ins are still visible regardless of tenant.
    assert "sds" in keys

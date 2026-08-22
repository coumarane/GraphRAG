"""/query <-> conversation persistence route tests."""

from __future__ import annotations

from uuid import uuid4

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


def test_query_without_conversation_id_auto_creates(client, tenant_headers) -> None:
    response = client.post(
        "/api/v1/query",
        json={"question": "What is this document about?"},
        headers=tenant_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["conversation_id"]

    detail = client.get(f"/api/v1/conversations/{body['conversation_id']}", headers=tenant_headers)
    assert detail.status_code == 200
    messages = detail.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "What is this document about?"
    assert messages[1]["content"] == body["answer"]


def test_second_turn_receives_persisted_history(client, tenant_headers) -> None:
    first = client.post(
        "/api/v1/query",
        json={"question": "First question."},
        headers=tenant_headers,
    )
    conversation_id = first.json()["conversation_id"]

    second = client.post(
        "/api/v1/query",
        json={"question": "Second question.", "conversation_id": conversation_id},
        headers=tenant_headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["conversation_id"] == conversation_id

    detail = client.get(f"/api/v1/conversations/{conversation_id}", headers=tenant_headers)
    messages = detail.json()["messages"]
    # 2 turns x (user + assistant) = 4 persisted messages.
    assert len(messages) == 4
    assert messages[0]["content"] == "First question."
    assert messages[2]["content"] == "Second question."


def test_client_sent_history_is_ignored_once_conversation_id_present(
    client, tenant_headers
) -> None:
    """Regression: a client-sent conversation_history must never override
    server-persisted history once conversation_id resolves — that would be a
    tamper vector into entity-pinning/clarification prompt construction, and
    would silently diverge from what's actually persisted.
    """
    first = client.post(
        "/api/v1/query",
        json={"question": "Real first question."},
        headers=tenant_headers,
    )
    conversation_id = first.json()["conversation_id"]

    client.post(
        "/api/v1/query",
        json={
            "question": "Second question.",
            "conversation_id": conversation_id,
            "conversation_history": [
                {"role": "user", "content": "FABRICATED prior turn"},
                {"role": "assistant", "content": "FABRICATED answer"},
            ],
        },
        headers=tenant_headers,
    )

    detail = client.get(f"/api/v1/conversations/{conversation_id}", headers=tenant_headers)
    contents = [m["content"] for m in detail.json()["messages"]]
    assert "FABRICATED prior turn" not in contents
    assert "Real first question." in contents


def test_query_upserts_unknown_conversation_id(client, tenant_headers) -> None:
    """A conversation_id the server hasn't seen yet (e.g. the frontend's
    background "create conversation" call hasn't landed) still works — the
    route creates it under that exact id rather than 404ing.
    """
    unknown_id = uuid4()
    response = client.post(
        "/api/v1/query",
        json={"question": "Fresh chat", "conversation_id": str(unknown_id)},
        headers=tenant_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["conversation_id"] == str(unknown_id)

    detail = client.get(f"/api/v1/conversations/{unknown_id}", headers=tenant_headers)
    assert detail.status_code == 200


def test_deleted_conversation_id_404s_on_next_query(client, tenant_headers) -> None:
    first = client.post(
        "/api/v1/query",
        json={"question": "Will be deleted."},
        headers=tenant_headers,
    )
    conversation_id = first.json()["conversation_id"]

    deleted = client.delete(f"/api/v1/conversations/{conversation_id}", headers=tenant_headers)
    assert deleted.status_code == 204

    got = client.get(f"/api/v1/conversations/{conversation_id}", headers=tenant_headers)
    assert got.status_code == 404


def test_patch_conversation_covers_rename_pin_archive_move(client, tenant_headers) -> None:
    created = client.post(
        "/api/v1/conversations", json={"title": "Original"}, headers=tenant_headers
    )
    conversation_id = created.json()["conversation_id"]

    renamed = client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"title": "Renamed"},
        headers=tenant_headers,
    )
    assert renamed.json()["title"] == "Renamed"
    assert renamed.json()["pinned"] is False

    pinned = client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"pinned": True},
        headers=tenant_headers,
    )
    assert pinned.json()["pinned"] is True
    assert pinned.json()["title"] == "Renamed"  # untouched by this patch

    archived = client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"archived": True},
        headers=tenant_headers,
    )
    assert archived.json()["archived"] is True

    project = client.post(
        "/api/v1/chat-projects", json={"name": "Folder"}, headers=tenant_headers
    )
    project_id = project.json()["project_id"]

    moved = client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"project_id": project_id},
        headers=tenant_headers,
    )
    assert moved.json()["project_id"] == project_id

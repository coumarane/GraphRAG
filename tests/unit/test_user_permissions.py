"""User permission / ABAC attribute management tests."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from enterprise_rag.api.app import create_app
from enterprise_rag.api.dependencies import get_tenant_context
from enterprise_rag.application.auth.permissions import (
    apply_user_permission_update,
    normalize_user_attributes,
)
from enterprise_rag.application.runtime import build_local_container
from enterprise_rag.config.settings import clear_settings_cache
from enterprise_rag.domain.auth.models import UserRecord, UserStatus
from enterprise_rag.domain.auth.passwords import hash_password
from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.persistence.users import InMemoryUserRepository


def test_normalize_syncs_admin_flag_with_role() -> None:
    member = normalize_user_attributes(
        {"admin": True, "can_ingest": False, "country": "FR"},
        role="member",
    )
    assert member["admin"] is False
    assert member["can_ingest"] is False
    assert member["country"] == "FR"

    admin = normalize_user_attributes({"can_ingest": True}, role="admin")
    assert admin["admin"] is True
    assert admin["can_ingest"] is True


def test_normalize_parses_groups_and_clearance() -> None:
    attrs = normalize_user_attributes(
        {
            "groups": "research, finance",
            "clearance_level": "7",
            "department": "R&D",
        },
        role="member",
        default_can_ingest=True,
    )
    assert attrs["groups"] == ["research", "finance"]
    assert attrs["clearance_level"] == 7
    assert attrs["department"] == "R&D"
    assert attrs["can_ingest"] is True


def test_demote_admin_clears_admin_attribute() -> None:
    user = UserRecord(
        user_id=new_id(),
        tenant_id=new_id(),
        email="lead@example.com",
        password_hash="x",
        role="admin",
        attributes={"admin": True, "can_ingest": True, "clearance_level": 9},
    )
    updated = apply_user_permission_update(user, role="member")
    assert updated.role == "member"
    assert updated.attributes["admin"] is False
    assert updated.attributes["can_ingest"] is True
    assert updated.attributes["clearance_level"] == 9


def test_patch_can_revoke_ingest_and_disable() -> None:
    user = UserRecord(
        user_id=new_id(),
        tenant_id=new_id(),
        email="ops@example.com",
        password_hash="x",
        role="member",
        attributes={"can_ingest": True, "country": "FR"},
    )
    updated = apply_user_permission_update(
        user,
        status=UserStatus.DISABLED,
        attributes={"can_ingest": False, "country": ""},
    )
    assert updated.status is UserStatus.DISABLED
    assert updated.is_active is False
    assert updated.attributes["can_ingest"] is False
    assert "country" not in updated.attributes


@pytest.mark.asyncio
async def test_in_memory_repo_syncs_membership_on_update() -> None:
    repo = InMemoryUserRepository()
    tenant_id = new_id()
    created = await repo.create(
        UserRecord(
            user_id=new_id(),
            tenant_id=tenant_id,
            email="member@example.com",
            password_hash=hash_password("super-secret-12"),
            role="member",
            attributes={"can_ingest": True},
        )
    )
    updated = await repo.update(
        created.model_copy(update={"attributes": {"can_ingest": False, "department": "legal"}})
    )
    membership = await repo.get_membership(user_id=updated.user_id, tenant_id=tenant_id)
    assert membership is not None
    assert membership.attributes["can_ingest"] is False
    assert membership.attributes["department"] == "legal"


def test_admin_patch_user_api() -> None:
    os.environ["AUTH_ENABLED"] = "false"
    clear_settings_cache()
    try:
        container = build_local_container()
        repo = InMemoryUserRepository()
        container.user_repo = repo
        app = create_app(container)
        tenant_id = uuid4()
        admin_id = new_id()
        member_id = new_id()

        async def seed() -> None:
            await repo.create(
                UserRecord(
                    user_id=admin_id,
                    tenant_id=tenant_id,
                    email="admin@example.com",
                    password_hash=hash_password("super-secret-12"),
                    role="admin",
                    attributes={"admin": True, "can_ingest": True},
                )
            )
            await repo.create(
                UserRecord(
                    user_id=member_id,
                    tenant_id=tenant_id,
                    email="reader@example.com",
                    password_hash=hash_password("super-secret-12"),
                    role="member",
                    attributes={"can_ingest": True, "clearance_level": 1},
                )
            )

        asyncio.run(seed())

        admin_tenant = TenantContext(
            tenant_id=tenant_id,
            tenant_key="demo",
            principal="admin@example.com",
            user_id=admin_id,
            roles=("admin",),
            attributes={"admin": True, "can_ingest": True},
            user_status="active",
        )

        async def override_tenant() -> TenantContext:
            return admin_tenant

        app.dependency_overrides[get_tenant_context] = override_tenant
        client = TestClient(app)

        listed = client.get("/api/v1/admin/users")
        assert listed.status_code == 200, listed.text
        emails = {item["email"] for item in listed.json()["items"]}
        assert "reader@example.com" in emails

        patched = client.patch(
            f"/api/v1/admin/users/{member_id}",
            json={
                "role": "member",
                "status": "active",
                "attributes": {
                    "can_ingest": False,
                    "clearance_level": 4,
                    "country": "FR",
                    "groups": "legal, research",
                },
            },
        )
        assert patched.status_code == 200, patched.text
        body = patched.json()
        assert body["attributes"]["can_ingest"] is False
        assert body["attributes"]["clearance_level"] == 4
        assert body["attributes"]["country"] == "FR"
        assert body["attributes"]["groups"] == ["legal", "research"]
        assert body["attributes"]["admin"] is False

        denied = client.patch(
            f"/api/v1/admin/users/{admin_id}",
            json={"role": "member"},
        )
        assert denied.status_code == 422
    finally:
        clear_settings_cache()

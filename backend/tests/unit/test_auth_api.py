"""Auth API login/me/bootstrap tests."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from enterprise_rag.api.app import create_app
from enterprise_rag.application.auth import AuthService
from enterprise_rag.application.runtime.container import ServiceContainer
from enterprise_rag.config.settings import clear_settings_cache
from enterprise_rag.domain.auth.passwords import hash_password
from enterprise_rag.domain.auth.models import UserRecord
from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.ingestion.records import TenantRecord
from enterprise_rag.infrastructure.persistence.memory import InMemoryTenantRepository
from enterprise_rag.infrastructure.persistence.users import InMemoryUserRepository


@pytest.fixture
def auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_JWT_SECRET", "unit-test-jwt-secret-key-32chars!!")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.mark.asyncio
async def test_login_me_and_protected_scope(auth_env: None) -> None:
    tenants = InMemoryTenantRepository()
    users = InMemoryUserRepository()
    tenant = await tenants.upsert(
        TenantRecord(
            tenant_id=new_id(),
            tenant_key="demo",
            display_name="Demo Workspace",
        )
    )
    await users.create(
        UserRecord(
            user_id=new_id(),
            tenant_id=tenant.tenant_id,
            email="admin@example.com",
            password_hash=hash_password("correct-horse-battery"),
            display_name="Admin",
            role="admin",
        )
    )
    container = ServiceContainer(
        tenant_repo=tenants,
        user_repo=users,
        auth_service=AuthService(
            users=users,
            tenants=tenants,
            jwt_secret=os.environ["AUTH_JWT_SECRET"],
            jwt_ttl_seconds=3600,
        ),
    )
    app = create_app(container)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        bad = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "wrong-password-1"},
        )
        assert bad.status_code == 401

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct-horse-battery"},
        )
        assert login.status_code == 200
        assert login.json()["user"]["email"] == "admin@example.com"
        assert "erag_session" in login.cookies

        me = await client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["tenant"]["tenant_key"] == "demo"

        denied = AsyncClient(transport=transport, base_url="http://test")
        async with denied as anonymous:
            bare = await anonymous.get("/api/v1/ops/dashboard")
            assert bare.status_code == 401

        ok = await client.get("/api/v1/ops/dashboard")
        assert ok.status_code == 200
        assert "documents_total" in ok.json()


@pytest.mark.asyncio
async def test_bootstrap_creates_admin(auth_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_BOOTSTRAP_EMAIL", "bootstrap@example.com")
    monkeypatch.setenv("AUTH_BOOTSTRAP_PASSWORD", "bootstrap-password-1")
    monkeypatch.setenv("AUTH_BOOTSTRAP_TENANT_KEY", "acme")
    monkeypatch.setenv("AUTH_BOOTSTRAP_TENANT_NAME", "Acme Corp")

    tenants = InMemoryTenantRepository()
    users = InMemoryUserRepository()
    service = AuthService(
        users=users,
        tenants=tenants,
        jwt_secret=os.environ["AUTH_JWT_SECRET"],
    )
    created = await service.bootstrap_from_env()
    assert created is True
    user = await users.get_by_email("bootstrap@example.com")
    assert user is not None
    assert user.role == "admin"
    tenant = await tenants.get_by_key("acme")
    assert tenant is not None
    assert tenant.display_name == "Acme Corp"
    assert await service.bootstrap_from_env() is False

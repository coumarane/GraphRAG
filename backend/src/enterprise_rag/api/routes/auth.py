"""Authentication HTTP routes."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict

from enterprise_rag.api.dependencies import ContainerDep, TenantDep
from enterprise_rag.application.auth import AuthService
from enterprise_rag.config.settings import Settings, get_settings
from enterprise_rag.domain.auth.models import CreateUserRequest, LoginRequest
from enterprise_rag.shared.exceptions import (
    AuthenticationError,
    ConfigurationError,
    RateLimitError,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_LOGIN_WINDOW_SECONDS = 60.0
_LOGIN_MAX_ATTEMPTS = 20
_login_attempts: dict[str, deque[float]] = defaultdict(deque)


class AuthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user: dict
    tenant: dict
    access_token: str | None = None


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _rate_limit_login(request: Request) -> None:
    ip = _client_ip(request)
    now = time.monotonic()
    bucket = _login_attempts[ip]
    while bucket and now - bucket[0] > _LOGIN_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= _LOGIN_MAX_ATTEMPTS:
        raise RateLimitError(
            "Too many login attempts. Try again shortly.",
            details={"retry_after_seconds": int(_LOGIN_WINDOW_SECONDS)},
        )
    bucket.append(now)


def _auth_service(container: ContainerDep, settings: Settings) -> AuthService:
    if container.auth_service is not None:
        return container.auth_service
    if container.user_repo is None:
        raise ConfigurationError("User repository is not configured")
    return AuthService(
        users=container.user_repo,
        tenants=container.tenant_repo,
        jwt_secret=settings.security.auth_jwt_secret,
        jwt_ttl_seconds=settings.security.auth_jwt_ttl_seconds,
    )


def _set_session_cookie(response: Response, *, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.security.auth_cookie_name,
        value=token,
        httponly=True,
        secure=settings.security.auth_cookie_secure
        or settings.app.environment.lower() in {"production", "prod", "staging"},
        samesite=settings.security.auth_cookie_samesite,  # type: ignore[arg-type]
        max_age=settings.security.auth_jwt_ttl_seconds,
        path="/",
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    container: ContainerDep,
) -> AuthResponse:
    # Recover from a prior failed DB transaction on the shared session.
    await container.rollback_db()
    _rate_limit_login(request)
    settings = get_settings()
    if not settings.security.auth_enabled:
        raise AuthenticationError("Authentication is not enabled on this deployment")
    service = _auth_service(container, settings)
    token, user, tenant = await service.login(
        email=str(payload.email),
        password=payload.password,
    )
    _set_session_cookie(response, token=token, settings=settings)
    await container.commit_db()
    return AuthResponse(
        user=user.model_dump(mode="json"),
        tenant=tenant.model_dump(mode="json"),
        access_token=token,
    )


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    settings = get_settings()
    response.delete_cookie(
        key=settings.security.auth_cookie_name,
        path="/",
    )
    return {"status": "ok"}


@router.get("/me", response_model=AuthResponse)
async def me(tenant: TenantDep, container: ContainerDep) -> AuthResponse:
    settings = get_settings()
    service = _auth_service(container, settings)
    user, tenant_view = await service.me(tenant)
    return AuthResponse(
        user=user.model_dump(mode="json"),
        tenant=tenant_view.model_dump(mode="json"),
    )


@router.post("/users", response_model=AuthResponse)
async def create_user(
    payload: CreateUserRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> AuthResponse:
    settings = get_settings()
    service = _auth_service(container, settings)
    user = await service.create_user(tenant, payload)
    tenant_view = (await service.me(tenant))[1]
    await container.commit_db()
    return AuthResponse(
        user=user.model_dump(mode="json"),
        tenant=tenant_view.model_dump(mode="json"),
    )

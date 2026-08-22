"""Users me + admin users/policies/quotas APIs."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from graph_rag.api.dependencies import ContainerDep, TenantDep
from graph_rag.application.auth.permissions import (
    apply_user_permission_update,
    normalize_user_attributes,
)
from graph_rag.application.authorization.gate import require_action
from graph_rag.application.authorization.service import subject_from_tenant
from graph_rag.domain.auth.models import CreateUserRequest, UserStatus
from graph_rag.domain.authorization.models import Action, PolicyDocument
from graph_rag.domain.ids import new_id
from graph_rag.domain.types import JsonValue
from graph_rag.shared.exceptions import NotFoundError, ValidationError

router = APIRouter(tags=["users"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])


class MeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID | None = None
    email: str | None = None
    tenant_id: UUID
    tenant_key: str | None = None
    status: str
    roles: list[str] = Field(default_factory=list)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    groups: list[str] = Field(default_factory=list)


class QuotaRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    period: str
    period_key: str
    limit: int
    used: int
    remaining: int
    reset_at: str


class PatchUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    role: str | None = None
    status: UserStatus | None = None
    attributes: dict[str, JsonValue] | None = None


class PolicyUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    document: PolicyDocument
    policy_id: UUID | None = None


class QuotaAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID | None = None
    plan_name: str = "default"
    overrides: dict[str, int] = Field(default_factory=dict)


@router.get("/users/me", response_model=MeResponse)
async def users_me(tenant: TenantDep) -> MeResponse:
    subject = subject_from_tenant(tenant)
    return MeResponse(
        user_id=subject.user_id,
        email=subject.email,
        tenant_id=subject.tenant_id,
        tenant_key=subject.tenant_key or tenant.tenant_key,
        status=subject.status,
        roles=list(subject.roles),
        attributes=dict(subject.attributes),
        groups=list(subject.groups),
    )


@router.get("/users/me/quotas")
async def users_me_quotas(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    quotas = container.require_quotas()
    rows = quotas.snapshot(tenant_id=tenant.tenant_id, user_id=tenant.user_id)
    return {"items": rows}


@router.get("/users/me/usage")
async def users_me_usage(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    quotas = container.require_quotas()
    events = [
        event
        for event in getattr(quotas, "usage_events", [])
        if event.get("tenant_id") == tenant.tenant_id
        and (tenant.user_id is None or event.get("user_id") == tenant.user_id)
    ]
    return {"items": events[-100:]}


@admin_router.get("/users")
async def admin_list_users(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    require_action(container.require_authorization(), tenant, Action.ADMIN_USERS)
    if container.user_repo is None:
        raise ValidationError("User repository is not configured")
    list_fn = getattr(container.user_repo, "list_by_tenant", None)
    if list_fn is None:
        raise ValidationError("User listing is not supported")
    users = await list_fn(tenant.tenant_id)
    return {
        "items": [
            {
                "user_id": str(user.user_id),
                "email": user.email,
                "display_name": user.display_name,
                "role": user.role,
                "status": user.status.value if hasattr(user.status, "value") else user.status,
                "is_active": bool(user.is_active),
                "attributes": dict(user.attributes),
            }
            for user in users
        ]
    }


@admin_router.post("/users", status_code=201)
async def admin_create_user(
    body: CreateUserRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, Any]:
    require_action(container.require_authorization(), tenant, Action.ADMIN_USERS)
    if container.auth_service is None:
        raise ValidationError("Auth service is not configured")
    # Prefer ABAC admin over legacy role check inside create_user.
    from graph_rag.domain.auth.models import UserRecord
    from graph_rag.domain.auth.passwords import hash_password

    if container.user_repo is None:
        raise ValidationError("User repository is not configured")
    attrs = normalize_user_attributes(
        dict(body.attributes),
        role=(body.role or "member").strip().casefold(),
        default_can_ingest=True,
    )
    record = UserRecord(
        user_id=new_id(),
        tenant_id=tenant.tenant_id,
        email=str(body.email).strip().casefold(),
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        role=(body.role or "member").strip().casefold(),
        status=UserStatus.ACTIVE,
        is_active=True,
        attributes=attrs,
    )
    created = await container.user_repo.create(record)
    await container.commit_db()
    return {
        "user_id": str(created.user_id),
        "email": created.email,
        "display_name": created.display_name,
        "role": created.role,
        "status": created.status.value,
        "is_active": created.is_active,
        "attributes": dict(created.attributes),
    }


@admin_router.patch("/users/{user_id}")
async def admin_patch_user(
    user_id: UUID,
    body: PatchUserRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, Any]:
    require_action(container.require_authorization(), tenant, Action.ADMIN_USERS)
    if container.user_repo is None:
        raise ValidationError("User repository is not configured")
    user = await container.user_repo.get_by_id(user_id)
    if user is None or user.tenant_id != tenant.tenant_id:
        raise NotFoundError("User not found", details={"user_id": str(user_id)})
    update = apply_user_permission_update(
        user,
        display_name=body.display_name,
        role=body.role,
        status=body.status,
        attributes=body.attributes,
    )
    if (
        tenant.user_id is not None
        and user.user_id == tenant.user_id
        and user.role == "admin"
        and update.role != "admin"
    ):
        raise ValidationError(
            "You cannot remove your own workspace admin access",
            details={"user_id": str(user_id)},
        )
    if (
        tenant.user_id is not None
        and user.user_id == tenant.user_id
        and update.status != UserStatus.ACTIVE
    ):
        raise ValidationError(
            "You cannot disable your own account",
            details={"user_id": str(user_id)},
        )
    updated = await container.user_repo.update(update)
    await container.commit_db()
    return {
        "user_id": str(updated.user_id),
        "email": updated.email,
        "display_name": updated.display_name,
        "role": updated.role,
        "status": updated.status.value,
        "is_active": updated.is_active,
        "attributes": dict(updated.attributes),
    }


@admin_router.get("/policies")
async def admin_list_policies(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    require_action(container.require_authorization(), tenant, Action.ADMIN_POLICIES)
    authz = container.require_authorization()
    items = authz.store.list_policies(tenant_id=tenant.tenant_id)
    global_items = authz.store.list_policies(tenant_id=None)
    return {
        "items": [
            {
                "policy_id": str(pid),
                "action": policy.action,
                "effect": policy.effect,
                "description": policy.description,
                "document": policy.model_dump(mode="json"),
            }
            for pid, policy in [*global_items, *items]
        ]
    }


@admin_router.post("/policies", status_code=201)
async def admin_upsert_policy(
    body: PolicyUpsertRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, Any]:
    require_action(container.require_authorization(), tenant, Action.ADMIN_POLICIES)
    authz = container.require_authorization()
    policy_id = authz.store.upsert(
        tenant_id=tenant.tenant_id,
        policy_id=body.policy_id,
        policy=body.document,
    )
    return {"policy_id": str(policy_id), "name": body.name}


@admin_router.get("/quotas")
async def admin_list_quotas(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    require_action(container.require_authorization(), tenant, Action.ADMIN_QUOTAS)
    quotas = container.require_quotas()
    return {
        "tenant": quotas.snapshot(tenant_id=tenant.tenant_id, user_id=None),
        "assignments": [
            a.model_dump(mode="json") for a in quotas.assignments if a.tenant_id == tenant.tenant_id
        ],
    }


@admin_router.post("/quotas", status_code=201)
async def admin_assign_quota(
    body: QuotaAssignmentRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, Any]:
    require_action(container.require_authorization(), tenant, Action.ADMIN_QUOTAS)
    quotas = container.require_quotas()
    assignment = quotas.assign_default(tenant_id=tenant.tenant_id, user_id=body.user_id)
    if body.overrides:
        assignment.overrides.update(body.overrides)
    return dict(assignment.model_dump(mode="json"))

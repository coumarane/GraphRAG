"""Deny-by-default AuthorizationService."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from graph_rag.application.authorization.engine import (
    default_seed_policies,
    evaluate_policy,
)
from graph_rag.domain.authorization.models import (
    Action,
    AuthorizationDecision,
    EnvironmentContext,
    PolicyDocument,
    ResourceContext,
    SubjectContext,
)
from graph_rag.domain.ids import new_id
from graph_rag.domain.tenant import TenantContext
from graph_rag.domain.types import JsonValue
from graph_rag.shared.exceptions import AuthorizationError


@dataclass
class InMemoryPolicyStore:
    """Tenant-scoped policy store (also used when DB policies are empty)."""

    _by_tenant: dict[UUID | None, list[tuple[UUID, PolicyDocument]]] = field(
        default_factory=dict
    )

    def seed_defaults(self, tenant_id: UUID | None = None) -> None:
        policies = [
            (new_id(), policy) for policy in default_seed_policies()
        ]
        self._by_tenant[tenant_id] = policies

    def list_policies(
        self,
        *,
        tenant_id: UUID | None,
        action: Action | None = None,
    ) -> list[tuple[UUID, PolicyDocument]]:
        items: list[tuple[UUID, PolicyDocument]] = []
        for key in (tenant_id, None):
            items.extend(self._by_tenant.get(key, []))
        if action is not None:
            items = [(pid, p) for pid, p in items if p.action == action.value]
        return items

    def upsert(
        self,
        *,
        tenant_id: UUID | None,
        policy_id: UUID | None,
        policy: PolicyDocument,
    ) -> UUID:
        pid = policy_id or new_id()
        bucket = self._by_tenant.setdefault(tenant_id, [])
        bucket = [(i, p) for i, p in bucket if i != pid]
        bucket.append((pid, policy))
        self._by_tenant[tenant_id] = bucket
        return pid


@dataclass
class PolicyAuthorizationService:
    """Evaluate structured JSON policies; deny by default."""

    store: InMemoryPolicyStore = field(default_factory=InMemoryPolicyStore)

    def __post_init__(self) -> None:
        if None not in self.store._by_tenant:
            self.store.seed_defaults(None)

    def authorize(
        self,
        *,
        subject: SubjectContext,
        action: Action,
        resource: ResourceContext | None = None,
        environment: EnvironmentContext | None = None,
    ) -> AuthorizationDecision:
        if subject.status not in {"active"} and not subject.is_service:
            return AuthorizationDecision(
                allowed=False,
                action=action,
                reason=f"subject status is {subject.status}",
            )
        # Service principals with matching tenant are allowed for operational actions.
        if subject.is_service and action in {
            Action.DOCUMENT_UPLOAD,
            Action.DOCUMENT_READ,
            Action.DOCUMENT_DELETE,
            Action.DOCUMENT_REINDEX,
            Action.QUERY_EXECUTE,
            Action.QUERY_CROSS_DOCUMENT,
            Action.GRAPH_QUERY,
        }:
            return AuthorizationDecision(
                allowed=True,
                action=action,
                reason="service principal",
            )
        if subject.attributes.get("admin") is True:
            return AuthorizationDecision(
                allowed=True,
                action=action,
                reason="admin attribute",
            )

        policies = self.store.list_policies(tenant_id=subject.tenant_id, action=action)
        for policy_id, policy in policies:
            if policy.effect != "allow":
                continue
            if evaluate_policy(
                policy,
                subject=subject,
                resource=resource,
                environment=environment,
            ):
                return AuthorizationDecision(
                    allowed=True,
                    action=action,
                    reason=policy.description or "policy matched",
                    matched_policy_id=policy_id,
                )
        return AuthorizationDecision(
            allowed=False,
            action=action,
            reason="deny by default: no matching allow policy",
        )

    def require(
        self,
        *,
        subject: SubjectContext,
        action: Action,
        resource: ResourceContext | None = None,
        environment: EnvironmentContext | None = None,
    ) -> AuthorizationDecision:
        decision = self.authorize(
            subject=subject,
            action=action,
            resource=resource,
            environment=environment,
        )
        if not decision.allowed:
            raise AuthorizationError(
                f"Not authorized for {action.value}",
                details={
                    "action": action.value,
                    "reason": decision.reason,
                    "tenant_id": str(subject.tenant_id),
                    "user_id": str(subject.user_id) if subject.user_id else None,
                },
            )
        return decision


def subject_from_tenant(tenant: TenantContext) -> SubjectContext:
    """Build SubjectContext from server-loaded TenantContext."""
    attrs: dict[str, JsonValue] = dict(tenant.attributes)
    if "admin" not in attrs and "admin" in tenant.roles:
        attrs["admin"] = True
    if "can_ingest" not in attrs:
        attrs["can_ingest"] = True
    if "clearance_level" not in attrs:
        attrs["clearance_level"] = 100 if attrs.get("admin") is True else 1
    groups = list(tenant.groups)
    raw_groups = attrs.get("groups")
    if isinstance(raw_groups, list):
        groups.extend(str(g) for g in raw_groups)
    return SubjectContext(
        user_id=tenant.user_id,
        tenant_id=tenant.tenant_id,
        tenant_key=tenant.tenant_key or "",
        email=tenant.principal,
        status=tenant.user_status,
        attributes=attrs,
        membership_attributes=dict(tenant.membership_attributes),
        roles=list(tenant.roles),
        groups=groups,
        security_labels=list(tenant.security_labels),
        is_service=tenant.is_service,
    )


def resource_from_document(
    *,
    tenant_id: UUID,
    document_id: UUID | None = None,
    owner_user_id: UUID | None = None,
    department: str | None = None,
    country: str | None = None,
    business_unit: str | None = None,
    classification: str | None = None,
    required_clearance: int | None = None,
    allowed_groups: list[str] | None = None,
    security_labels: list[str] | None = None,
) -> ResourceContext:
    return ResourceContext(
        resource_type="document",
        resource_id=document_id,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        department=department,
        country=country,
        business_unit=business_unit,
        classification=classification,
        required_clearance=required_clearance,
        allowed_groups=list(allowed_groups or []),
        security_labels=list(security_labels or []),
    )

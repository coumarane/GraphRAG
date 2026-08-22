"""Structured ABAC policy evaluation (no executable user code)."""

from __future__ import annotations

from typing import Any

from graph_rag.domain.authorization.models import (
    EnvironmentContext,
    PolicyDocument,
    PolicyWhenClause,
    ResourceContext,
    SubjectContext,
)


def _resolve_path(root: dict[str, Any], path: str) -> Any:
    current: Any = root
    for part in path.split("."):
        if current is None:
            return None
        if isinstance(current, dict):
            if part not in current:
                return _Missing
            current = current[part]
        else:
            if not hasattr(current, part):
                return _Missing
            current = getattr(current, part)
    return current


class _MissingType:
    pass


_Missing = _MissingType()


def _as_context_dict(
    subject: SubjectContext,
    resource: ResourceContext | None,
    environment: EnvironmentContext | None,
) -> dict[str, Any]:
    return {
        "subject": {
            "user_id": str(subject.user_id) if subject.user_id else None,
            "tenant_id": str(subject.tenant_id),
            "tenant_key": subject.tenant_key,
            "email": subject.email,
            "status": subject.status,
            "attributes": dict(subject.attributes),
            "membership_attributes": dict(subject.membership_attributes),
            "roles": list(subject.roles),
            "groups": list(subject.groups),
            "security_labels": list(subject.security_labels),
            "is_service": subject.is_service,
            "clearance_level": subject.attributes.get("clearance_level"),
            "country": subject.attributes.get("country"),
            "department": subject.attributes.get("department"),
            "admin": subject.attributes.get("admin"),
            "can_ingest": subject.attributes.get("can_ingest"),
        },
        "resource": {
            "resource_type": resource.resource_type if resource else None,
            "resource_id": str(resource.resource_id) if resource and resource.resource_id else None,
            "tenant_id": str(resource.tenant_id) if resource and resource.tenant_id else None,
            "owner_user_id": (
                str(resource.owner_user_id) if resource and resource.owner_user_id else None
            ),
            "department": resource.department if resource else None,
            "country": resource.country if resource else None,
            "business_unit": resource.business_unit if resource else None,
            "classification": resource.classification if resource else None,
            "required_clearance": resource.required_clearance if resource else None,
            "allowed_groups": list(resource.allowed_groups) if resource else [],
            "security_labels": list(resource.security_labels) if resource else [],
            "attributes": dict(resource.attributes) if resource else {},
        },
        "environment": {
            "correlation_id": environment.correlation_id if environment else None,
            "ip": environment.ip if environment else None,
            "attributes": dict(environment.attributes) if environment else {},
        },
    }


def _compare(op: str, left: Any, right: Any) -> bool:
    if left is _Missing or right is _Missing:
        return False
    if op == "eq":
        return bool(left == right)
    if op == "neq":
        return bool(left != right)
    if op == "gte":
        try:
            return float(left) >= float(right)
        except (TypeError, ValueError):
            return False
    if op == "lte":
        try:
            return float(left) <= float(right)
        except (TypeError, ValueError):
            return False
    if op == "in":
        if not isinstance(right, list | tuple | set):
            return False
        return left in right
    if op == "contains_any":
        left_set = set(left) if isinstance(left, list | tuple | set) else set()
        right_set = set(right) if isinstance(right, list | tuple | set) else set()
        return bool(left_set & right_set)
    if op == "exists":
        return left is not None and left is not _Missing
    if op == "bool_true":
        return left is True or left == "true" or left == 1
    return False


def evaluate_clause(clause: PolicyWhenClause, ctx: dict[str, Any]) -> bool:
    left = _resolve_path(ctx, clause.attr)
    if clause.ref is not None:
        right = _resolve_path(ctx, clause.ref)
        # Unset resource constraint → no requirement (subject still fail-closed if missing).
        if right is None or right is _Missing:
            return True
        # Empty allowed_groups / lists mean unconstrained.
        if isinstance(right, list | tuple | set) and len(right) == 0:
            return True
    else:
        right = clause.value
    # Missing subject attribute fails closed.
    if left is _Missing:
        return False
    return _compare(clause.op, left, right)


def evaluate_policy(
    policy: PolicyDocument,
    *,
    subject: SubjectContext,
    resource: ResourceContext | None = None,
    environment: EnvironmentContext | None = None,
) -> bool:
    """Return True when all when-clauses match (AND). Missing fields fail closed."""
    ctx = _as_context_dict(subject, resource, environment)
    if not policy.when:
        return True
    return all(evaluate_clause(clause, ctx) for clause in policy.when)


def default_seed_policies() -> list[PolicyDocument]:
    """Default deny-by-default allow policies for a tenant."""
    return [
        PolicyDocument(
            effect="allow",
            action="document.read",
            description="Same-tenant read with clearance/country/group checks",
            when=[
                PolicyWhenClause(attr="subject.tenant_id", op="eq", ref="resource.tenant_id"),
                PolicyWhenClause(
                    attr="subject.attributes.clearance_level",
                    op="gte",
                    ref="resource.required_clearance",
                ),
                PolicyWhenClause(
                    attr="subject.attributes.country",
                    op="eq",
                    ref="resource.country",
                ),
                PolicyWhenClause(
                    attr="subject.groups",
                    op="contains_any",
                    ref="resource.allowed_groups",
                ),
            ],
        ),
        PolicyDocument(
            effect="allow",
            action="document.upload",
            description="Ingest when can_ingest is true",
            when=[
                PolicyWhenClause(attr="subject.attributes.can_ingest", op="bool_true"),
            ],
        ),
        PolicyDocument(
            effect="allow",
            action="document.delete",
            description="Delete when admin or can_ingest",
            when=[
                PolicyWhenClause(attr="subject.attributes.can_ingest", op="bool_true"),
            ],
        ),
        PolicyDocument(
            effect="allow",
            action="document.reindex",
            description="Reindex when can_ingest",
            when=[
                PolicyWhenClause(attr="subject.attributes.can_ingest", op="bool_true"),
            ],
        ),
        PolicyDocument(
            effect="allow",
            action="query.execute",
            description="Same-tenant query",
            when=[
                PolicyWhenClause(attr="subject.status", op="eq", value="active"),
            ],
        ),
        PolicyDocument(
            effect="allow",
            action="query.cross_document",
            description="Cross-document query for active users",
            when=[
                PolicyWhenClause(attr="subject.status", op="eq", value="active"),
            ],
        ),
        PolicyDocument(
            effect="allow",
            action="graph.query",
            description="Graph query for active users",
            when=[
                PolicyWhenClause(attr="subject.status", op="eq", value="active"),
            ],
        ),
        PolicyDocument(
            effect="allow",
            action="admin.users",
            description="Admin users",
            when=[PolicyWhenClause(attr="subject.attributes.admin", op="bool_true")],
        ),
        PolicyDocument(
            effect="allow",
            action="admin.policies",
            description="Admin policies",
            when=[PolicyWhenClause(attr="subject.attributes.admin", op="bool_true")],
        ),
        PolicyDocument(
            effect="allow",
            action="admin.quotas",
            description="Admin quotas",
            when=[PolicyWhenClause(attr="subject.attributes.admin", op="bool_true")],
        ),
        PolicyDocument(
            effect="allow",
            action="admin.tenant",
            description="Admin tenant",
            when=[PolicyWhenClause(attr="subject.attributes.admin", op="bool_true")],
        ),
        PolicyDocument(
            effect="allow",
            action="admin.plugins",
            description="Admin plugins",
            when=[PolicyWhenClause(attr="subject.attributes.admin", op="bool_true")],
        ),
        PolicyDocument(
            effect="allow",
            action="admin.settings",
            description="Admin settings",
            when=[PolicyWhenClause(attr="subject.attributes.admin", op="bool_true")],
        ),
    ]

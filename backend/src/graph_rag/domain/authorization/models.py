"""ABAC subject/resource/policy models."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.types import JsonValue


class Action(StrEnum):
    """Canonical authorization actions."""

    DOCUMENT_UPLOAD = "document.upload"
    DOCUMENT_READ = "document.read"
    DOCUMENT_DELETE = "document.delete"
    DOCUMENT_REINDEX = "document.reindex"
    DOCUMENT_MANAGE = "document.manage"
    QUERY_EXECUTE = "query.execute"
    QUERY_CROSS_DOCUMENT = "query.cross_document"
    GRAPH_QUERY = "graph.query"
    ADMIN_USERS = "admin.users"
    ADMIN_POLICIES = "admin.policies"
    ADMIN_QUOTAS = "admin.quotas"
    ADMIN_TENANT = "admin.tenant"
    ADMIN_PLUGINS = "admin.plugins"
    ADMIN_SETTINGS = "admin.settings"


class SubjectContext(BaseModel):
    """Authenticated principal attributes used for ABAC evaluation."""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID | None = None
    tenant_id: UUID
    tenant_key: str
    email: str | None = None
    status: str = "active"
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    membership_attributes: dict[str, JsonValue] = Field(default_factory=dict)
    roles: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    security_labels: list[str] = Field(default_factory=list)
    is_service: bool = False


class ResourceContext(BaseModel):
    """Resource attributes for ABAC evaluation."""

    model_config = ConfigDict(extra="forbid")

    resource_type: str = "document"
    resource_id: UUID | None = None
    tenant_id: UUID | None = None
    owner_user_id: UUID | None = None
    department: str | None = None
    country: str | None = None
    business_unit: str | None = None
    classification: str | None = None
    required_clearance: int | None = None
    allowed_groups: list[str] = Field(default_factory=list)
    security_labels: list[str] = Field(default_factory=list)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class EnvironmentContext(BaseModel):
    """Request environment attributes (time, IP, etc.)."""

    model_config = ConfigDict(extra="forbid")

    correlation_id: str | None = None
    ip: str | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class PolicyWhenClause(BaseModel):
    """Single AND-ed policy predicate."""

    model_config = ConfigDict(extra="forbid")

    attr: str
    op: str
    value: JsonValue | None = None
    ref: str | None = None


class PolicyDocument(BaseModel):
    """Structured allow/deny policy (no executable code)."""

    model_config = ConfigDict(extra="forbid")

    effect: str = "allow"
    action: str
    when: list[PolicyWhenClause] = Field(default_factory=list)
    description: str | None = None


class AuthorizationDecision(BaseModel):
    """Outcome of an authorization check."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    action: Action
    reason: str
    matched_policy_id: UUID | None = None

"""ORM models for ABAC policies, memberships, and quotas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from graph_rag.domain.ids import new_id
from graph_rag.infrastructure.persistence.postgres.base import Base, TimestampMixin, utc_now


class TenantMembershipModel(Base, TimestampMixin):
    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_tenant_memberships_user_tenant"),
    )

    membership_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    attributes: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)


class AuthorizationPolicyModel(Base, TimestampMixin):
    __tablename__ = "authorization_policies"

    policy_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    effect: Mapped[str] = mapped_column(String(16), nullable=False, default="allow")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    document: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)


class PolicyVersionModel(Base):
    __tablename__ = "policy_versions"
    __table_args__ = (
        UniqueConstraint("policy_id", "version_number", name="uq_policy_versions_number"),
    )

    version_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("authorization_policies.policy_id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=utc_now,
    )


class QuotaPlanModel(Base, TimestampMixin):
    __tablename__ = "quota_plans"

    plan_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    limits: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        nullable=False,
        default=dict,
    )


class QuotaAssignmentModel(Base, TimestampMixin):
    __tablename__ = "quota_assignments"

    assignment_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("quota_plans.plan_id", ondelete="CASCADE"),
        nullable=False,
    )
    period: Mapped[str] = mapped_column(String(32), nullable=False, default="month")
    overrides: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class UsageCounterModel(Base):
    __tablename__ = "usage_counters"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "metric",
            "period",
            "period_key",
            name="uq_usage_counters_scope",
        ),
    )

    counter_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=True,
    )
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    period: Mapped[str] = mapped_column(String(32), nullable=False)
    period_key: Mapped[str] = mapped_column(String(32), nullable=False)
    used: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reserved: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=utc_now,
        onupdate=utc_now,
    )


class QuotaReservationModel(Base, TimestampMixin):
    __tablename__ = "quota_reservations"

    reservation_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    period: Mapped[str] = mapped_column(String(32), nullable=False)
    period_key: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="reserved")


class QuotaUsageEventModel(Base):
    __tablename__ = "quota_usage_events"

    event_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    usage_type: Mapped[str] = mapped_column(String(64), nullable=False, default="actual")
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reservation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("quota_reservations.reservation_id", ondelete="SET NULL"),
        nullable=True,
    )
    document_id: Mapped[UUID | None] = mapped_column(nullable=True)
    query_id: Mapped[UUID | None] = mapped_column(nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=utc_now,
    )

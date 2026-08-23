"""ORM models for the durable plugin registry and its configuration.

Not the runtime source of truth for what's installed -- that's
``application/plugins/registry.py::PluginRegistry`` (in-memory, rebuilt each
process start from core descriptors + entry-point discovery). These tables
are the durable, queryable counterpart: admin audit history (when was a
plugin toggled) and persisted configuration, not a second registry
implementation.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from graph_rag.domain.ids import new_id
from graph_rag.infrastructure.persistence.postgres.base import Base, TimestampMixin


class PluginModel(Base, TimestampMixin):
    """Plugin registry row (not tenant-owned; global, like ``TenantModel``)."""

    __tablename__ = "plugins"
    __table_args__ = (
        UniqueConstraint("capability", "plugin_name", name="uq_plugins_capability_plugin_name"),
    )

    plugin_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    capability: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    plugin_name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="0.0.0")
    trust_tier: Mapped[str] = mapped_column(String(16), nullable=False, default="community")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        nullable=False,
        default=dict,
    )


class PluginConfigurationModel(Base, TimestampMixin):
    """Plugin configuration row.

    ``tenant_id`` is nullable: NULL means a global default, a real UUID means
    a per-tenant override. Phase 1 only ever writes NULL rows (this codebase
    has no per-tenant settings resolution layer yet) -- the nullable column
    exists so per-tenant overrides can be added later without a further
    migration.
    """

    __tablename__ = "plugin_configuration"
    __table_args__ = (
        UniqueConstraint("plugin_id", "tenant_id", name="uq_plugin_configuration_plugin_tenant"),
    )

    config_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    plugin_id: Mapped[UUID] = mapped_column(
        ForeignKey("plugins.plugin_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)

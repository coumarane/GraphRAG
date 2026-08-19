"""PostgreSQL persistence adapters."""

from enterprise_rag.infrastructure.persistence.postgres.base import Base
from enterprise_rag.infrastructure.persistence.postgres.repositories import (
    SqlAlchemyDocumentRepository,
    SqlAlchemyIngestionRepository,
    SqlAlchemyTenantRepository,
)
from enterprise_rag.infrastructure.persistence.postgres.rls import (
    clear_tenant_context,
    require_matching_tenant,
    set_tenant_context,
)
from enterprise_rag.infrastructure.persistence.postgres.session import (
    LockedAsyncProxy,
    create_engine,
    create_engine_from_url,
    create_session_factory,
    session_scope,
)

__all__ = [
    "Base",
    "LockedAsyncProxy",
    "SqlAlchemyDocumentRepository",
    "SqlAlchemyIngestionRepository",
    "SqlAlchemyTenantRepository",
    "clear_tenant_context",
    "create_engine",
    "create_engine_from_url",
    "create_session_factory",
    "require_matching_tenant",
    "session_scope",
    "set_tenant_context",
]

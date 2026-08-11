"""Request-scoped usage correlation context."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Iterator
from uuid import UUID

_usage_context: ContextVar["UsageContext | None"] = ContextVar(
    "enterprise_rag_usage_context", default=None
)


@dataclass(frozen=True, slots=True)
class UsageContext:
    """Correlation fields attached to metered model calls."""

    tenant_id: UUID
    document_id: UUID | None = None
    ingestion_run_id: UUID | None = None
    query_id: UUID | None = None
    correlation_id: str | None = None


def get_usage_context() -> UsageContext | None:
    return _usage_context.get()


def set_usage_context(ctx: UsageContext | None) -> Token["UsageContext | None"]:
    return _usage_context.set(ctx)


def reset_usage_context(token: Token["UsageContext | None"]) -> None:
    _usage_context.reset(token)


@contextmanager
def usage_context(
    *,
    tenant_id: UUID,
    document_id: UUID | None = None,
    ingestion_run_id: UUID | None = None,
    query_id: UUID | None = None,
    correlation_id: str | None = None,
) -> Iterator[UsageContext]:
    """Bind usage context for the current task/request."""
    ctx = UsageContext(
        tenant_id=tenant_id,
        document_id=document_id,
        ingestion_run_id=ingestion_run_id,
        query_id=query_id,
        correlation_id=correlation_id,
    )
    token = set_usage_context(ctx)
    try:
        yield ctx
    finally:
        reset_usage_context(token)

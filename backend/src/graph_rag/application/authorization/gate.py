"""Shared authz + quota gates for use cases and routes."""

from __future__ import annotations

import inspect
from typing import Any
from uuid import UUID

from graph_rag.application.authorization.filters import document_is_authorized
from graph_rag.application.authorization.service import (
    PolicyAuthorizationService,
    resource_from_document,
    subject_from_tenant,
)
from graph_rag.domain.authorization.models import Action
from graph_rag.domain.ingestion.records import DocumentRecord
from graph_rag.domain.quotas.models import QuotaMetric, QuotaPeriod, QuotaReservation
from graph_rag.domain.tenant import TenantContext


def require_action(
    authz: PolicyAuthorizationService,
    tenant: TenantContext,
    action: Action,
    *,
    document: DocumentRecord | None = None,
) -> None:
    subject = subject_from_tenant(tenant)
    resource = None
    if document is not None:
        resource = resource_from_document(
            tenant_id=document.tenant_id,
            document_id=document.document_id,
            owner_user_id=document.owner_user_id,
            department=document.department,
            country=document.country,
            business_unit=document.business_unit,
            classification=document.classification,
            required_clearance=document.required_clearance,
            allowed_groups=document.allowed_groups,
            security_labels=document.security_labels,
        )
    elif action in {Action.DOCUMENT_UPLOAD, Action.QUERY_EXECUTE, Action.GRAPH_QUERY}:
        resource = resource_from_document(tenant_id=tenant.tenant_id)
    authz.require(subject=subject, action=action, resource=resource)


async def reserve_quota(
    quotas: Any,
    tenant: TenantContext,
    *,
    metric: QuotaMetric,
    quantity: int,
    period: QuotaPeriod | None = None,
) -> QuotaReservation:
    """Reserve quota on either the in-memory or Postgres service.

    ``PostgresQuotaService.reserve`` is a coroutine. Calling it without
    awaiting made ``reservation.reservation_id`` raise AttributeError after a
    successful search and turned the HTTP response into a 500.
    """
    result = quotas.reserve(
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        metric=metric,
        quantity=quantity,
        period=period,
    )
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, QuotaReservation):
        raise TypeError("Quota reserve did not return a reservation")
    return result


async def commit_quota(
    quotas: Any,
    *,
    reservation_id: UUID,
    actual_quantity: int,
) -> None:
    result = quotas.commit(reservation_id=reservation_id, actual_quantity=actual_quantity)
    if inspect.isawaitable(result):
        await result


async def release_quota(quotas: Any, *, reservation_id: UUID) -> None:
    result = quotas.release(reservation_id=reservation_id)
    if inspect.isawaitable(result):
        await result


def ensure_document_read(
    authz: PolicyAuthorizationService,
    tenant: TenantContext,
    document: DocumentRecord,
) -> None:
    require_action(authz, tenant, Action.DOCUMENT_READ, document=document)


def authorized_document_ids(
    authz: PolicyAuthorizationService,
    tenant: TenantContext,
    documents: list[DocumentRecord],
) -> list[UUID]:
    return [
        doc.document_id
        for doc in documents
        if document_is_authorized(authz, tenant, doc)
    ]

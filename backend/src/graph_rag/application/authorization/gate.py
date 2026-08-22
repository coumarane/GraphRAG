"""Shared authz + quota gates for use cases and routes."""

from __future__ import annotations

from uuid import UUID

from graph_rag.application.authorization.filters import document_is_authorized
from graph_rag.application.authorization.service import (
    PolicyAuthorizationService,
    resource_from_document,
    subject_from_tenant,
)
from graph_rag.application.quotas.service import InMemoryQuotaService
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


def reserve_quota(
    quotas: InMemoryQuotaService,
    tenant: TenantContext,
    *,
    metric: QuotaMetric,
    quantity: int,
    period: QuotaPeriod | None = None,
) -> QuotaReservation:
    return quotas.reserve(
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        metric=metric,
        quantity=quantity,
        period=period,
    )


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

"""ABAC helpers for document visibility filtering."""

from __future__ import annotations

from graph_rag.application.authorization.service import (
    PolicyAuthorizationService,
    resource_from_document,
    subject_from_tenant,
)
from graph_rag.domain.authorization.models import Action
from graph_rag.domain.ingestion.records import DocumentRecord
from graph_rag.domain.tenant import TenantContext


def document_is_authorized(
    authz: PolicyAuthorizationService,
    tenant: TenantContext,
    document: DocumentRecord,
    *,
    action: Action = Action.DOCUMENT_READ,
) -> bool:
    subject = subject_from_tenant(tenant)
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
    return authz.authorize(subject=subject, action=action, resource=resource).allowed


def filter_authorized_documents(
    authz: PolicyAuthorizationService,
    tenant: TenantContext,
    documents: list[DocumentRecord],
    *,
    action: Action = Action.DOCUMENT_READ,
) -> list[DocumentRecord]:
    return [
        document
        for document in documents
        if document_is_authorized(authz, tenant, document, action=action)
    ]

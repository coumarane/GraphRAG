"""Unit tests for ABAC policy engine, authorization, and quotas."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from enterprise_rag.application.authorization.engine import (
    default_seed_policies,
    evaluate_policy,
)
from enterprise_rag.application.authorization.filters import document_is_authorized
from enterprise_rag.application.authorization.service import (
    PolicyAuthorizationService,
    resource_from_document,
    subject_from_tenant,
)
from enterprise_rag.application.quotas.service import InMemoryQuotaService
from enterprise_rag.domain.authorization.models import (
    Action,
    PolicyDocument,
    PolicyWhenClause,
    ResourceContext,
    SubjectContext,
)
from enterprise_rag.domain.ingestion.records import DocumentRecord
from enterprise_rag.domain.quotas.models import QuotaMetric, QuotaPeriod
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import AuthorizationError, QuotaExceededError


def _tenant(**kwargs: object) -> TenantContext:
    base = {
        "tenant_id": uuid4(),
        "tenant_key": "demo",
        "principal": "user@example.com",
        "user_id": uuid4(),
        "roles": ("member",),
        "attributes": {},
    }
    base.update(kwargs)
    return TenantContext(**base)  # type: ignore[arg-type]


def test_clearance_deny_and_allow() -> None:
    authz = PolicyAuthorizationService()
    tenant = _tenant(attributes={"clearance_level": 2, "can_ingest": True})
    subject = subject_from_tenant(tenant)
    low = resource_from_document(
        tenant_id=tenant.tenant_id,
        document_id=uuid4(),
        required_clearance=1,
    )
    high = resource_from_document(
        tenant_id=tenant.tenant_id,
        document_id=uuid4(),
        required_clearance=5,
    )
    assert authz.authorize(
        subject=subject, action=Action.DOCUMENT_READ, resource=low
    ).allowed
    assert not authz.authorize(
        subject=subject, action=Action.DOCUMENT_READ, resource=high
    ).allowed


def test_country_and_group_deny() -> None:
    authz = PolicyAuthorizationService()
    tenant = _tenant(
        attributes={"clearance_level": 10, "country": "FR", "groups": ["finance"]},
        groups=("finance",),
    )
    subject = subject_from_tenant(tenant)
    wrong_country = resource_from_document(
        tenant_id=tenant.tenant_id,
        document_id=uuid4(),
        country="US",
        required_clearance=1,
    )
    wrong_group = resource_from_document(
        tenant_id=tenant.tenant_id,
        document_id=uuid4(),
        country="FR",
        allowed_groups=["legal"],
        required_clearance=1,
    )
    ok = resource_from_document(
        tenant_id=tenant.tenant_id,
        document_id=uuid4(),
        country="FR",
        allowed_groups=["finance"],
        required_clearance=1,
    )
    assert not authz.authorize(
        subject=subject, action=Action.DOCUMENT_READ, resource=wrong_country
    ).allowed
    assert not authz.authorize(
        subject=subject, action=Action.DOCUMENT_READ, resource=wrong_group
    ).allowed
    assert authz.authorize(
        subject=subject, action=Action.DOCUMENT_READ, resource=ok
    ).allowed


def test_tenant_mismatch_deny() -> None:
    authz = PolicyAuthorizationService()
    tenant = _tenant(attributes={"clearance_level": 10, "can_ingest": True})
    subject = subject_from_tenant(tenant)
    other = resource_from_document(tenant_id=uuid4(), document_id=uuid4())
    assert not authz.authorize(
        subject=subject, action=Action.DOCUMENT_READ, resource=other
    ).allowed


def test_require_raises() -> None:
    authz = PolicyAuthorizationService()
    tenant = _tenant(attributes={"admin": False, "can_ingest": False})
    subject = subject_from_tenant(tenant)
    # Override default can_ingest injection
    subject = subject.model_copy(update={"attributes": {"can_ingest": False, "admin": False}})
    with pytest.raises(AuthorizationError):
        authz.require(subject=subject, action=Action.DOCUMENT_UPLOAD)


def test_document_filter_excludes_unauthorized() -> None:
    authz = PolicyAuthorizationService()
    tenant_id = uuid4()
    tenant = _tenant(
        tenant_id=tenant_id,
        attributes={"clearance_level": 1, "country": "FR"},
    )
    allowed = DocumentRecord(
        document_id=uuid4(),
        tenant_id=tenant_id,
        required_clearance=1,
        country="FR",
    )
    denied = DocumentRecord(
        document_id=uuid4(),
        tenant_id=tenant_id,
        required_clearance=9,
        country="FR",
    )
    assert document_is_authorized(authz, tenant, allowed)
    assert not document_is_authorized(authz, tenant, denied)


def test_policy_engine_operators() -> None:
    policy = PolicyDocument(
        effect="allow",
        action="document.read",
        when=[
            PolicyWhenClause(attr="subject.attributes.level", op="gte", value=3),
            PolicyWhenClause(attr="subject.groups", op="contains_any", value=["a", "b"]),
            PolicyWhenClause(attr="subject.attributes.flag", op="bool_true"),
        ],
    )
    subject = SubjectContext(
        tenant_id=uuid4(),
        tenant_key="t",
        attributes={"level": 5, "flag": True},
        groups=["b"],
    )
    assert evaluate_policy(policy, subject=subject, resource=ResourceContext())
    assert default_seed_policies()


def test_quota_reserve_commit_and_exhaust() -> None:
    quotas = InMemoryQuotaService()
    tenant_id = uuid4()
    user_id = uuid4()
    quotas.assign_default(tenant_id=tenant_id, user_id=None)
    # Tiny override for documents
    for assignment in quotas.assignments:
        if assignment.tenant_id == tenant_id and assignment.user_id is None:
            assignment.overrides["documents:month"] = 2
    r1 = quotas.reserve(
        tenant_id=tenant_id,
        user_id=user_id,
        metric=QuotaMetric.DOCUMENTS,
        quantity=1,
        period=QuotaPeriod.MONTH,
    )
    quotas.commit(reservation_id=r1.reservation_id, actual_quantity=1)
    r2 = quotas.reserve(
        tenant_id=tenant_id,
        user_id=user_id,
        metric=QuotaMetric.DOCUMENTS,
        quantity=1,
        period=QuotaPeriod.MONTH,
    )
    quotas.commit(reservation_id=r2.reservation_id, actual_quantity=1)
    with pytest.raises(QuotaExceededError) as exc:
        quotas.reserve(
            tenant_id=tenant_id,
            user_id=user_id,
            metric=QuotaMetric.DOCUMENTS,
            quantity=1,
            period=QuotaPeriod.MONTH,
        )
    assert exc.value.details["limit"] == 2
    assert exc.value.http_status == 429


def test_quota_release_on_failure_path() -> None:
    quotas = InMemoryQuotaService()
    tenant_id = uuid4()
    quotas.assign_default(tenant_id=tenant_id)
    for assignment in quotas.assignments:
        if assignment.tenant_id == tenant_id:
            assignment.overrides["documents:month"] = 1
    reservation = quotas.reserve(
        tenant_id=tenant_id,
        user_id=None,
        metric=QuotaMetric.DOCUMENTS,
        quantity=1,
        period=QuotaPeriod.MONTH,
    )
    quotas.release(reservation_id=reservation.reservation_id)
    # Capacity available again
    quotas.reserve(
        tenant_id=tenant_id,
        user_id=None,
        metric=QuotaMetric.DOCUMENTS,
        quantity=1,
        period=QuotaPeriod.MONTH,
    )


def test_concurrent_quota_reserve() -> None:
    quotas = InMemoryQuotaService()
    tenant_id = uuid4()
    quotas.assign_default(tenant_id=tenant_id)
    for assignment in quotas.assignments:
        if assignment.tenant_id == tenant_id:
            assignment.overrides["queries:day"] = 5

    def _one() -> bool:
        try:
            quotas.reserve(
                tenant_id=tenant_id,
                user_id=uuid4(),
                metric=QuotaMetric.QUERIES,
                quantity=1,
                period=QuotaPeriod.DAY,
            )
            return True
        except QuotaExceededError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: _one(), range(20)))
    assert sum(1 for ok in results if ok) == 5
    assert sum(1 for ok in results if not ok) == 15


def test_tenant_ceiling_over_user() -> None:
    quotas = InMemoryQuotaService()
    tenant_id = uuid4()
    user_id = uuid4()
    quotas.assign_default(tenant_id=tenant_id, user_id=None)
    quotas.assign_default(tenant_id=tenant_id, user_id=user_id)
    for assignment in quotas.assignments:
        key = "documents:month"
        if assignment.user_id is None:
            assignment.overrides[key] = 1
        else:
            assignment.overrides[key] = 100
    quotas.reserve(
        tenant_id=tenant_id,
        user_id=user_id,
        metric=QuotaMetric.DOCUMENTS,
        quantity=1,
        period=QuotaPeriod.MONTH,
    )
    with pytest.raises(QuotaExceededError):
        quotas.reserve(
            tenant_id=tenant_id,
            user_id=user_id,
            metric=QuotaMetric.DOCUMENTS,
            quantity=1,
            period=QuotaPeriod.MONTH,
        )


def test_admin_bypass() -> None:
    authz = PolicyAuthorizationService()
    tenant = _tenant(attributes={"admin": True})
    subject = subject_from_tenant(tenant)
    assert authz.authorize(subject=subject, action=Action.ADMIN_USERS).allowed

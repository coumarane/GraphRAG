"""TenantContext unit tests."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.exceptions import TenantError


def test_tenant_context_frozen() -> None:
    ctx = TenantContext(tenant_id=uuid4(), tenant_key="demo", roles=("admin",))
    assert ctx.tenant_key == "demo"
    with pytest.raises(ValidationError):
        ctx.tenant_key = "other"  # type: ignore[misc]


def test_ensure_authorized_rejects_nil_uuid() -> None:
    ctx = TenantContext(tenant_id=UUID(int=0))
    with pytest.raises(TenantError):
        ctx.ensure_authorized()

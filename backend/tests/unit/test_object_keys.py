"""Object key and filename sanitization tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

from graph_rag.domain.ids import new_id
from graph_rag.domain.storage import (
    assert_tenant_object_prefix,
    original_object_key,
    sanitize_filename,
)
from graph_rag.shared.exceptions import ValidationError


def test_sanitize_filename_strips_paths() -> None:
    assert sanitize_filename("../../etc/passwd.pdf") == "passwd.pdf"
    assert sanitize_filename(r"C:\\tmp\\report.docx") == "report.docx"


def test_sanitize_filename_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        sanitize_filename("***")


def test_original_object_key_uses_tenant_prefix() -> None:
    tenant_id = new_id()
    document_id = new_id()
    version_id = new_id()
    key = original_object_key(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        filename="My Report (final).PDF",
    )
    assert key.startswith(
        f"tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/original/"
    )
    assert "Report" in key or "report" in key.lower() or "My_Report" in key
    assert_tenant_object_prefix(key, tenant_id)


def test_assert_tenant_object_prefix_rejects_cross_tenant() -> None:
    with pytest.raises(ValidationError):
        assert_tenant_object_prefix(
            f"tenants/{uuid4()}/documents/{uuid4()}/versions/{uuid4()}/original/a.pdf",
            new_id(),
        )

"""Object-store key construction and filename sanitization."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from uuid import UUID

from enterprise_rag.shared.exceptions import ValidationError

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_FILENAME_LENGTH = 180


def sanitize_filename(filename: str) -> str:
    """Return a path-safe filename component (never trust client input)."""
    raw = filename.strip().replace("\\", "/")
    name = PurePosixPath(raw).name
    if not name or name in {".", ".."}:
        raise ValidationError(
            "Filename is empty or invalid",
            details={"filename": filename},
        )
    if "/" in name or "\\" in name:
        raise ValidationError(
            "Filename must not contain path separators",
            details={"filename": filename},
        )
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", name).strip("._")
    if not cleaned:
        raise ValidationError(
            "Filename sanitization produced an empty result",
            details={"filename": filename},
        )
    if len(cleaned) > _MAX_FILENAME_LENGTH:
        stem = PurePosixPath(cleaned).stem[: _MAX_FILENAME_LENGTH - 20]
        suffix = PurePosixPath(cleaned).suffix[:20]
        cleaned = f"{stem}{suffix}"
    return cleaned


def original_object_key(
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    filename: str,
) -> str:
    """Build the object key for an original uploaded document."""
    safe = sanitize_filename(filename)
    return f"tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/original/{safe}"


def page_object_key(
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    page_number: int,
) -> str:
    if page_number < 1:
        raise ValidationError("page_number must be >= 1")
    return (
        f"tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/pages/{page_number}.png"
    )


def asset_object_key(
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    asset_id: UUID,
    extension: str,
) -> str:
    ext = extension.lstrip(".").lower()
    if not ext or "/" in ext or "\\" in ext:
        raise ValidationError("Invalid asset extension", details={"extension": extension})
    return (
        f"tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/assets/{asset_id}.{ext}"
    )


def normalized_document_object_key(
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
) -> str:
    return (
        f"tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/"
        "normalized/document.json"
    )


def derived_markdown_object_key(
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
) -> str:
    return f"tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/derived/document.md"


def assert_tenant_object_prefix(object_key: str, tenant_id: UUID) -> None:
    """Fail closed when an object key escapes the tenant prefix."""
    expected = f"tenants/{tenant_id}/"
    if not object_key.startswith(expected):
        raise ValidationError(
            "Object key is outside the authorized tenant prefix",
            details={"object_key": object_key, "tenant_id": str(tenant_id)},
        )
    if ".." in object_key.split("/"):
        raise ValidationError(
            "Object key must not contain parent-directory segments",
            details={"object_key": object_key},
        )

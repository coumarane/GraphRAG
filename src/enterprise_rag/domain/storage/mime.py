"""MIME type policy for source intake."""

from __future__ import annotations

from enterprise_rag.shared.exceptions import UnsupportedDocumentError, ValidationError

DEFAULT_ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "image/png",
        "image/jpeg",
        "image/tiff",
        "image/webp",
        "text/html",
        "text/markdown",
        "text/plain",
    }
)


def assert_allowed_mime_type(
    mime_type: str,
    *,
    allowed: frozenset[str] | set[str] | list[str] | None = None,
) -> str:
    """Validate MIME against the allowlist and return the normalized type."""
    normalized = mime_type.strip().lower()
    if ";" in normalized:
        normalized = normalized.split(";", 1)[0].strip()
    allow = frozenset(allowed) if allowed is not None else DEFAULT_ALLOWED_MIME_TYPES
    if normalized not in allow:
        raise UnsupportedDocumentError(
            "MIME type is not allowed",
            details={"mime_type": normalized, "allowed": sorted(allow)},
        )
    return normalized


def assert_within_size_limit(byte_size: int, *, max_upload_bytes: int) -> None:
    if byte_size < 0:
        raise ValidationError("byte_size cannot be negative")
    if byte_size == 0:
        raise ValidationError("Empty files are not allowed")
    if byte_size > max_upload_bytes:
        raise ValidationError(
            "File exceeds maximum upload size",
            details={"byte_size": byte_size, "max_upload_bytes": max_upload_bytes},
        )

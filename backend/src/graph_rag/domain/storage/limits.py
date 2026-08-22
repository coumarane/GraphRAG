"""Upload and parse resource limit helpers."""

from __future__ import annotations

import zipfile
from io import BytesIO

from graph_rag.shared.exceptions import UnsupportedDocumentError, ValidationError

DEFAULT_MAX_PAGES = 2_000
DEFAULT_MAX_ZIP_ENTRIES = 10_000
DEFAULT_MAX_ZIP_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_COMPRESSION_RATIO = 100.0


def assert_within_page_limit(page_count: int, *, max_pages: int = DEFAULT_MAX_PAGES) -> None:
    """Reject documents that exceed the configured page ceiling."""
    if page_count < 0:
        raise ValidationError("page_count cannot be negative")
    if page_count > max_pages:
        raise ValidationError(
            "Document exceeds maximum page count",
            details={"page_count": page_count, "max_pages": max_pages},
        )


def assert_safe_zip_archive(
    data: bytes,
    *,
    max_entries: int = DEFAULT_MAX_ZIP_ENTRIES,
    max_uncompressed_bytes: int = DEFAULT_MAX_ZIP_UNCOMPRESSED_BYTES,
    max_compression_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO,
) -> None:
    """Reject zip bombs / path-traversal members in OOXML packages."""
    if not data.startswith(b"PK\x03\x04"):
        return
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise UnsupportedDocumentError("ZIP/OOXML package is corrupt") from exc

    if len(infos) > max_entries:
        raise UnsupportedDocumentError(
            "ZIP archive has too many entries",
            details={"entries": len(infos), "max_entries": max_entries},
        )

    total_uncompressed = 0
    compressed_total = max(len(data), 1)
    for info in infos:
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/"):
            raise UnsupportedDocumentError(
                "ZIP archive contains unsafe member path",
                details={"member": name},
            )
        total_uncompressed += max(info.file_size, 0)
        if total_uncompressed > max_uncompressed_bytes:
            raise UnsupportedDocumentError(
                "ZIP uncompressed size exceeds limit",
                details={
                    "uncompressed_bytes": total_uncompressed,
                    "max_uncompressed_bytes": max_uncompressed_bytes,
                },
            )

    ratio = total_uncompressed / compressed_total
    if ratio > max_compression_ratio:
        raise UnsupportedDocumentError(
            "ZIP compression ratio exceeds archive-bomb threshold",
            details={
                "ratio": round(ratio, 2),
                "max_compression_ratio": max_compression_ratio,
            },
        )


__all__ = [
    "DEFAULT_MAX_COMPRESSION_RATIO",
    "DEFAULT_MAX_PAGES",
    "DEFAULT_MAX_ZIP_ENTRIES",
    "DEFAULT_MAX_ZIP_UNCOMPRESSED_BYTES",
    "assert_safe_zip_archive",
    "assert_within_page_limit",
]

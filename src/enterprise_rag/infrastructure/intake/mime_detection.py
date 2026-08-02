"""Byte-based MIME detection for the supported intake allowlist."""

from __future__ import annotations

import zipfile
from io import BytesIO

from enterprise_rag.domain.storage.limits import assert_safe_zip_archive
from enterprise_rag.domain.storage.mime import assert_allowed_mime_type
from enterprise_rag.shared.exceptions import UnsupportedDocumentError, ValidationError

# Office Open XML packages are ZIP containers; refine via internal paths.
_OOXML_TYPES = {
    "word/": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "ppt/": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xl/": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def detect_mime_type(data: bytes, *, filename: str | None = None) -> str:
    """Detect MIME type from content bytes (not client-declared type)."""
    if not data:
        raise ValidationError("Cannot detect MIME type of empty content")

    detected: str | None = None
    if data.startswith(b"%PDF"):
        detected = "application/pdf"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        detected = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        detected = "image/jpeg"
    elif data.startswith((b"II*\x00", b"MM\x00*")):
        detected = "image/tiff"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        detected = "image/webp"
    elif data.startswith(b"PK\x03\x04"):
        detected = _detect_ooxml(data)
    else:
        detected = _detect_textish(data, filename=filename)

    if detected is None:
        raise UnsupportedDocumentError(
            "Unable to detect a supported MIME type from content",
            details={"filename": filename},
        )
    return assert_allowed_mime_type(detected)


def _detect_ooxml(data: bytes) -> str | None:
    assert_safe_zip_archive(data)
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = {name.replace("\\", "/") for name in archive.namelist()}
    except zipfile.BadZipFile as exc:
        raise UnsupportedDocumentError(
            "ZIP/OOXML package is corrupt or unsupported",
        ) from exc

    if "[Content_Types].xml" not in names:
        raise UnsupportedDocumentError("ZIP archive is not a supported OOXML document")

    for marker, mime in _OOXML_TYPES.items():
        if any(name.startswith(marker) for name in names):
            return mime
    raise UnsupportedDocumentError("OOXML package type is not supported")


def _detect_textish(data: bytes, *, filename: str | None) -> str | None:
    sample = data[:4096]
    if b"\x00" in sample:
        return None
    try:
        text = sample.decode("utf-8")
    except UnicodeDecodeError:
        return None

    lowered = text.lstrip().lower()
    if lowered.startswith("<!doctype html") or lowered.startswith("<html"):
        return "text/html"

    suffix = (filename or "").rsplit(".", 1)[-1].lower() if filename and "." in filename else ""
    if suffix in {"md", "markdown"}:
        return "text/markdown"
    if suffix in {"html", "htm"}:
        return "text/html"
    if suffix in {"txt", "text"} or suffix == "":
        return "text/plain"
    # UTF-8 text without a known extension defaults to plain text.
    return "text/plain"

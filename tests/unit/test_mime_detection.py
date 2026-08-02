"""MIME detection and allowlist tests."""

from __future__ import annotations

import pytest

from enterprise_rag.domain.storage.mime import assert_allowed_mime_type, assert_within_size_limit
from enterprise_rag.infrastructure.intake.mime_detection import detect_mime_type
from enterprise_rag.shared.exceptions import UnsupportedDocumentError, ValidationError


def test_detect_pdf_and_png() -> None:
    assert detect_mime_type(b"%PDF-1.7\n...", filename="a.pdf") == "application/pdf"
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    assert detect_mime_type(png, filename="a.png") == "image/png"


def test_detect_plain_text_and_html() -> None:
    assert detect_mime_type(b"hello world", filename="notes.txt") == "text/plain"
    assert detect_mime_type(b"<!DOCTYPE html><html></html>", filename="x.html") == "text/html"


def test_reject_disallowed_and_oversize() -> None:
    with pytest.raises(UnsupportedDocumentError):
        assert_allowed_mime_type("application/zip")
    with pytest.raises(ValidationError):
        assert_within_size_limit(0, max_upload_bytes=10)
    with pytest.raises(ValidationError):
        assert_within_size_limit(11, max_upload_bytes=10)
